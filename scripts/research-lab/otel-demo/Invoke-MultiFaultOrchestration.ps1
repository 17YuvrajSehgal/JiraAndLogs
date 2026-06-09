<#
.SYNOPSIS
    Orchestrate multi-fault scenarios (L2 concurrent / L3 cascade / L4 compound)
    for the OTel Demo cross-app dataset.

.DESCRIPTION
    The OB v5-large dataset is single-fault-per-run by construction. The OTel
    Demo dataset adds graded-difficulty multi-fault scenarios per docs5/00 §5.5.
    This script implements the three composition modes:

    L2 — concurrent     Two independent faults applied sequentially within
                        seconds, then both held for the active-fault window,
                        then both restored.
    L3 — cascade        Primary fault applied; secondary is EMERGENT (we
                        observe it, we do not inject it). After
                        cascade_emergence_window seconds, the active_fault
                        window timer starts. Only the primary is restored.
    L4 — compound       Two faults with mixed primitive types; behaves like
                        concurrent.

    Input is a sidecar JSON file (referenced by execution.components_file in
    the scenario YAML) because the existing scenario YAML parser does not
    support list-of-objects. The JSON shape is:

        {
          "cascade_emergence_window_seconds": 30,
          "fault_components": [
            { "action": "ScaleDeployment", "target_name": "kafka",
              "replicas": 0, "restore_replicas": 1,
              "is_primary_cause": true },
            { "action": "observation_only", "expected_target": "checkout",
              "expected_signal": "kafka producer error",
              "is_primary_cause": false }
          ]
        }

    Primitives implemented inline (kept independent from OB run-scenario.ps1
    per docs5/01 Rule R2):
      - ScaleDeployment
      - Flagd
      - SetEnv
      - ChaosMeshChaos (applies/deletes a chaos-mesh CR manifest; used by the
        L4 compound to mix a network fault with a resource fault) — added 2026-06-09
      - observation_only (records expected secondary in restore manifest)

.PARAMETER ComponentsFile
    Path to the sidecar JSON file listing fault_components.

.PARAMETER CompositionType
    One of: concurrent | cascade | compound_primitive

.PARAMETER DurationSeconds
    Active-fault window duration.

.PARAMETER Namespace
    Kubernetes namespace.

.PARAMETER CascadeEmergenceWindowSeconds
    For cascade mode: time to wait after primary application before starting
    the active-fault timer. Default 30 if not set.

.PARAMETER SkipRestore
    Don't restore the faults after duration.

.OUTPUTS
    JSON restore manifest with per-component metadata.

.NOTES
    Idempotent. Each primitive captures original state before applying so
    restores are always derivable.

    The orchestrator is invoked by scripts/research-lab/run-scenario.ps1's
    MultiFault dispatch branch; it is not typically called directly.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ComponentsFile,

    [Parameter(Mandatory = $true)]
    [ValidateSet("concurrent", "cascade", "compound_primitive")]
    [string]$CompositionType,

    [Parameter(Mandatory = $true)]
    [int]$DurationSeconds,

    [Parameter(Mandatory = $true)]
    [string]$Namespace,

    [int]$CascadeEmergenceWindowSeconds = 30,

    [switch]$SkipRestore
)

$ErrorActionPreference = "Stop"

Import-Module (Join-Path (Join-Path (Split-Path -Parent $PSScriptRoot) "lib") "ResearchLab.psm1") -Force

# ---------------------------------------------------------------------------
# Inline primitive helpers (intentional duplication of OB logic per Rule R2)
# ---------------------------------------------------------------------------

function Apply-ScaleDeployment {
    param([object]$Component, [string]$TargetNamespace)
    $target = $Component.target_name
    if (-not $target) { throw "ScaleDeployment requires target_name" }
    $deployment = Invoke-ResearchLabKubectlJson -ArgumentList @(
        "get", "deployment", $target, "-n", $TargetNamespace, "-o", "json"
    )
    $originalReplicas = [int]$deployment.spec.replicas
    $replicas = if ($null -ne $Component.replicas) { [int]$Component.replicas } else { 0 }

    Invoke-ResearchLabKubectlText -ArgumentList @(
        "scale", "deployment/$target", "-n", $TargetNamespace, "--replicas=$replicas"
    ) | Out-Host
    if ($replicas -gt 0) {
        Invoke-ResearchLabKubectlText -ArgumentList @(
            "rollout", "status", "deployment/$target", "-n", $TargetNamespace, "--timeout=240s"
        ) | Out-Host
    }
    return @{
        type = "ScaleDeployment"
        target_name = $target
        original_replicas = $originalReplicas
        applied_replicas = $replicas
        is_primary_cause = [bool]$Component.is_primary_cause
    }
}

function Restore-ScaleDeployment {
    param([hashtable]$Restore, [string]$TargetNamespace)
    $target = $Restore.target_name
    $replicas = $Restore.original_replicas
    Invoke-ResearchLabKubectlText -ArgumentList @(
        "scale", "deployment/$target", "-n", $TargetNamespace, "--replicas=$replicas"
    ) | Out-Host
    if ($replicas -gt 0) {
        Invoke-ResearchLabKubectlText -ArgumentList @(
            "rollout", "status", "deployment/$target", "-n", $TargetNamespace, "--timeout=240s"
        ) | Out-Host
    }
}

function Apply-Flagd {
    param([object]$Component, [string]$TargetNamespace)
    $flag = $Component.flagd_flag
    if (-not $flag) { throw "Flagd component requires flagd_flag" }
    $variant = if ($Component.flagd_variant) { $Component.flagd_variant } else { "on" }
    $cmName = if ($Component.flagd_configmap_name) { $Component.flagd_configmap_name } else { "flagd-config" }
    $cmKey = if ($Component.flagd_configmap_key) { $Component.flagd_configmap_key } else { "demo.flagd.json" }

    $cm = Invoke-ResearchLabKubectlJson -ArgumentList @(
        "get", "configmap", $cmName, "-n", $TargetNamespace, "-o", "json"
    )
    $parsed = $cm.data.$cmKey | ConvertFrom-Json -Depth 50
    $originalVariant = [string]$parsed.flags.$flag.defaultVariant
    $parsed.flags.$flag.defaultVariant = $variant
    $newJson = $parsed | ConvertTo-Json -Depth 50
    $patch = @{ data = @{ $cmKey = $newJson } } | ConvertTo-Json -Depth 50 -Compress
    Invoke-ResearchLabKubectlText -ArgumentList @(
        "patch", "configmap", $cmName, "-n", $TargetNamespace, "--type=merge", "-p", $patch
    ) | Out-Host
    Start-Sleep -Seconds 3
    return @{
        type = "Flagd"
        flagd_flag = $flag
        original_variant = $originalVariant
        applied_variant = $variant
        configmap_name = $cmName
        configmap_key = $cmKey
        is_primary_cause = [bool]$Component.is_primary_cause
    }
}

function Restore-Flagd {
    param([hashtable]$Restore, [string]$TargetNamespace)
    $cm = Invoke-ResearchLabKubectlJson -ArgumentList @(
        "get", "configmap", $Restore.configmap_name, "-n", $TargetNamespace, "-o", "json"
    )
    $parsed = $cm.data.($Restore.configmap_key) | ConvertFrom-Json -Depth 50
    $parsed.flags.($Restore.flagd_flag).defaultVariant = $Restore.original_variant
    $newJson = $parsed | ConvertTo-Json -Depth 50
    $patch = @{ data = @{ $Restore.configmap_key = $newJson } } | ConvertTo-Json -Depth 50 -Compress
    Invoke-ResearchLabKubectlText -ArgumentList @(
        "patch", "configmap", $Restore.configmap_name, "-n", $TargetNamespace, "--type=merge", "-p", $patch
    ) | Out-Host
    Start-Sleep -Seconds 3
}

function Apply-SetEnv {
    param([object]$Component, [string]$TargetNamespace)
    $target = $Component.target_name
    if (-not $target) { throw "SetEnv requires target_name" }
    $envValues = $Component.env
    if (-not $envValues) { throw "SetEnv requires env (object/hashtable)" }

    $deployment = Invoke-ResearchLabKubectlJson -ArgumentList @(
        "get", "deployment", $target, "-n", $TargetNamespace, "-o", "json"
    )
    $originalEnv = @{}
    foreach ($container in @($deployment.spec.template.spec.containers)) {
        foreach ($e in @($container.env)) {
            if ($e.name) { $originalEnv[[string]$e.name] = $e.value }
        }
    }

    $args = @("set", "env", "deployment/$target", "-n", $TargetNamespace)
    foreach ($prop in $envValues.PSObject.Properties) {
        $args += "$($prop.Name)=$($prop.Value)"
    }
    Invoke-ResearchLabKubectlText -ArgumentList $args | Out-Host
    Invoke-ResearchLabKubectlText -ArgumentList @(
        "rollout", "status", "deployment/$target", "-n", $TargetNamespace, "--timeout=240s"
    ) | Out-Host

    # Convert applied env to plain hashtable for restore-time iteration.
    $appliedEnv = @{}
    foreach ($prop in $envValues.PSObject.Properties) { $appliedEnv[$prop.Name] = $prop.Value }

    return @{
        type = "SetEnv"
        target_name = $target
        original_env = $originalEnv
        applied_env = $appliedEnv
        is_primary_cause = [bool]$Component.is_primary_cause
    }
}

function Restore-SetEnv {
    param([hashtable]$Restore, [string]$TargetNamespace)
    $target = $Restore.target_name
    $args = @("set", "env", "deployment/$target", "-n", $TargetNamespace)
    foreach ($key in $Restore.applied_env.Keys) {
        if ($Restore.original_env.Contains($key)) {
            $args += "$key=$($Restore.original_env[$key])"
        } else {
            $args += "$key-"
        }
    }
    Invoke-ResearchLabKubectlText -ArgumentList $args | Out-Host
    Invoke-ResearchLabKubectlText -ArgumentList @(
        "rollout", "status", "deployment/$target", "-n", $TargetNamespace, "--timeout=240s"
    ) | Out-Host
}

function Apply-ChaosMeshChaos {
    # 2026-06-09: added so L4 compound scenarios can mix a chaos-mesh network
    # fault with a flagd/scale/env fault. Additive to this otel-demo fork only
    # (Rule R2) — the OB-shared run-scenario.ps1 ChaosMeshChaos path is unchanged.
    # The component supplies `chaos_manifest` (repo-relative path to a chaos-mesh
    # CR yaml); we apply it and capture name/kind/namespace for restore.
    param([object]$Component, [string]$TargetNamespace)
    $manifest = $Component.chaos_manifest
    if (-not $manifest) { throw "ChaosMeshChaos component requires chaos_manifest" }
    $repoRoot = Get-ResearchLabRepoRoot
    $manifestPath = if ([System.IO.Path]::IsPathRooted($manifest)) { $manifest } else { Join-ResearchLabPath @($repoRoot, $manifest) }
    if (-not (Test-Path -LiteralPath $manifestPath)) { throw "ChaosMeshChaos manifest not found: $manifestPath" }

    $chaosKind = (Get-Content -LiteralPath $manifestPath | Select-String -Pattern "^kind:" | Select-Object -First 1).Line -replace "^kind:\s*", ""
    $chaosName = (Get-Content -LiteralPath $manifestPath | Select-String -Pattern "^\s+name:" | Select-Object -First 1).Line -replace "^\s+name:\s*", ""
    $chaosNs   = (Get-Content -LiteralPath $manifestPath | Select-String -Pattern "^\s+namespace:" | Select-Object -First 1).Line -replace "^\s+namespace:\s*", ""

    Write-Host "ChaosMeshChaos component applying: $manifestPath ($($chaosKind.ToLower())/$chaosName in $chaosNs)"
    Invoke-ResearchLabKubectlText -ArgumentList @("apply", "-f", $manifestPath) | Out-Host
    Start-Sleep -Seconds 5
    return @{
        type = "ChaosMeshChaos"
        manifest_path = $manifestPath
        chaos_kind = $chaosKind
        chaos_name = $chaosName
        chaos_namespace = $chaosNs
        is_primary_cause = [bool]$Component.is_primary_cause
    }
}

function Restore-ChaosMeshChaos {
    # Bounded delete with a finalizer-removal fallback, mirroring the hardening
    # in run-scenario.ps1: chaos-mesh CRs carry finalizers that block deletion
    # until AllRecovered=True, so a failed inject would otherwise hang here.
    param([hashtable]$Restore, [string]$TargetNamespace)
    $manifestPath = $Restore.manifest_path
    $chaosResource = "$($Restore.chaos_kind.ToLower())/$($Restore.chaos_name)"
    $chaosNs = $Restore.chaos_namespace
    Write-Host "ChaosMeshChaos component deleting (bounded 45s): $chaosResource"
    $deleteOk = $false
    try {
        Invoke-ResearchLabKubectlText -ArgumentList @(
            "delete", "-f", $manifestPath, "--ignore-not-found=true", "--timeout=45s"
        ) | Out-Host
        $deleteOk = $true
    } catch {
        Write-Warning "Bounded delete failed for ${chaosResource}: $($_.Exception.Message)"
    }
    if (-not $deleteOk) {
        Write-Warning "Patching finalizers off $chaosResource in $chaosNs to force removal."
        try {
            Invoke-ResearchLabKubectlText -ArgumentList @(
                "patch", $chaosResource, "-n", $chaosNs, "--type=merge", "-p", '{"metadata":{"finalizers":[]}}'
            ) | Out-Host
            Invoke-ResearchLabKubectlText -ArgumentList @(
                "delete", $chaosResource, "-n", $chaosNs, "--ignore-not-found=true"
            ) | Out-Host
        } catch {
            Write-Warning "Finalizer fallback also failed for ${chaosResource}: $($_.Exception.Message)"
        }
    }
}

function Apply-Component {
    param([object]$Component, [string]$TargetNamespace)
    switch ($Component.action) {
        "ScaleDeployment" { return Apply-ScaleDeployment -Component $Component -TargetNamespace $TargetNamespace }
        "Flagd"           { return Apply-Flagd           -Component $Component -TargetNamespace $TargetNamespace }
        "SetEnv"          { return Apply-SetEnv          -Component $Component -TargetNamespace $TargetNamespace }
        "ChaosMeshChaos"  { return Apply-ChaosMeshChaos  -Component $Component -TargetNamespace $TargetNamespace }
        "observation_only" {
            return @{
                type = "observation_only"
                expected_target = $Component.expected_target
                expected_signal = $Component.expected_signal
                injected = $false
                is_primary_cause = [bool]$Component.is_primary_cause
            }
        }
        default { throw "Unsupported multi-fault component action: $($Component.action)" }
    }
}

function Restore-Component {
    param([hashtable]$Restore, [string]$TargetNamespace)
    switch ($Restore.type) {
        "ScaleDeployment" { Restore-ScaleDeployment -Restore $Restore -TargetNamespace $TargetNamespace }
        "Flagd"           { Restore-Flagd           -Restore $Restore -TargetNamespace $TargetNamespace }
        "SetEnv"          { Restore-SetEnv          -Restore $Restore -TargetNamespace $TargetNamespace }
        "ChaosMeshChaos"  { Restore-ChaosMeshChaos  -Restore $Restore -TargetNamespace $TargetNamespace }
        "observation_only" { }   # nothing to restore
        default { Write-Warning "Unknown restore type: $($Restore.type); skipping" }
    }
}

# ---------------------------------------------------------------------------
# Load components JSON
# ---------------------------------------------------------------------------

if (-not (Test-Path -LiteralPath $ComponentsFile)) {
    throw "Components file not found: $ComponentsFile"
}
$componentsDoc = Get-Content -LiteralPath $ComponentsFile -Raw | ConvertFrom-Json -Depth 50
$components = $componentsDoc.fault_components
if (-not $components -or $components.Count -lt 2) {
    throw "Components file must define fault_components array with at least 2 entries"
}

if ($componentsDoc.cascade_emergence_window_seconds) {
    $CascadeEmergenceWindowSeconds = [int]$componentsDoc.cascade_emergence_window_seconds
}

Write-Host "MultiFault: composition_type=$CompositionType n=$($components.Count) duration=$DurationSeconds s ns=$Namespace"

$restoreManifest = [ordered]@{
    composition_type = $CompositionType
    namespace = $Namespace
    duration_seconds = $DurationSeconds
    cascade_emergence_window_seconds = $null
    component_restores = @()
}

# ---------------------------------------------------------------------------
# Apply by composition type
# ---------------------------------------------------------------------------

if ($CompositionType -eq "concurrent" -or $CompositionType -eq "compound_primitive") {
    foreach ($comp in $components) {
        $applied = Apply-Component -Component $comp -TargetNamespace $Namespace
        $restoreManifest.component_restores += $applied
    }
    Write-Host "MultiFault: all components applied; sleeping $DurationSeconds s"
    Start-Sleep -Seconds $DurationSeconds

    if (-not $SkipRestore) {
        for ($i = $restoreManifest.component_restores.Count - 1; $i -ge 0; $i--) {
            $r = $restoreManifest.component_restores[$i]
            if ($r -is [hashtable]) {
                Restore-Component -Restore $r -TargetNamespace $Namespace
            }
        }
    }

} elseif ($CompositionType -eq "cascade") {
    $restoreManifest.cascade_emergence_window_seconds = $CascadeEmergenceWindowSeconds

    $primary = $components[0]
    $secondary = $components[1]

    Write-Host "MultiFault cascade: applying primary action=$($primary.action) target=$($primary.target_name)"
    $primaryRestore = Apply-Component -Component $primary -TargetNamespace $Namespace
    $restoreManifest.component_restores += $primaryRestore

    Write-Host "MultiFault cascade: waiting $CascadeEmergenceWindowSeconds s for secondary ($($secondary.expected_target)) to manifest organically"
    Start-Sleep -Seconds $CascadeEmergenceWindowSeconds

    # Record secondary (observation_only) in the manifest
    $secondaryRecord = Apply-Component -Component $secondary -TargetNamespace $Namespace
    $restoreManifest.component_restores += $secondaryRecord

    Write-Host "MultiFault cascade: active-fault window $DurationSeconds s"
    Start-Sleep -Seconds $DurationSeconds

    if (-not $SkipRestore) {
        Write-Host "MultiFault cascade: restoring primary"
        if ($primaryRestore -is [hashtable]) {
            Restore-Component -Restore $primaryRestore -TargetNamespace $Namespace
        }
    }

} else {
    throw "Unsupported composition_type: $CompositionType"
}

# ---------------------------------------------------------------------------
# Emit restore manifest to stdout (caller captures as JSON)
# ---------------------------------------------------------------------------
$restoreManifest | ConvertTo-Json -Depth 10

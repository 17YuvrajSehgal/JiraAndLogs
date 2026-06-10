<#
.SYNOPSIS
    Flip an OTel Demo flagd feature flag for the duration of an active-fault
    window, then restore the original value.

.DESCRIPTION
    flagd watches a ConfigMap for its flag definitions. To change a flag at
    runtime we read the ConfigMap, modify the named flag's `defaultVariant`,
    re-apply, and let flagd pick up the change (~2-3 seconds).

    Flow:
      1. Read current ConfigMap (capture original variant for restore)
      2. Set defaultVariant = -Variant
      3. Apply via kubectl patch
      4. Settle 3s for flagd to pick up the change
      5. Sleep -DurationSeconds (active-fault window)
      6. Restore original defaultVariant (unless -SkipRestore)

.PARAMETER FlagName
    The flag to flip (e.g. "paymentFailure", "kafkaQueueProblems").

.PARAMETER Variant
    Target variant name (e.g. "on", "100%", "10sec", "1000x"). Must match a
    variant defined in the flag's `variants` map.

.PARAMETER DurationSeconds
    How long to keep the flag flipped before restore.

.PARAMETER Namespace
    Kubernetes namespace. Default "otel-demo-research".

.PARAMETER ConfigMapName
    flagd ConfigMap name. Default "otel-demo-flagd-config" (the helm chart's
    standard name for opentelemetry-demo).

.PARAMETER ConfigMapKey
    Key within the ConfigMap that holds the flagd JSON. Default
    "demo.flagd.json".

.PARAMETER SkipRestore
    Don't restore after duration. Useful only for debugging; scenario runs
    must always restore.

.OUTPUTS
    Restore-state hashtable with original_variant so callers can restore
    out-of-band if SkipRestore is set.

.NOTES
    Isolation: this script affects ONLY the named OTel Demo flagd ConfigMap.
    It does not touch the OB cluster or OB ConfigMaps.

    Idempotent within a single run: re-applying the same variant has no
    semantic effect (flagd just re-reads the ConfigMap).
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$FlagName,

    [Parameter(Mandatory = $true)]
    [string]$Variant,

    [Parameter(Mandatory = $true)]
    [int]$DurationSeconds,

    [string]$Namespace = "otel-demo-research",
    # Default for the upstream helm chart; verify on first deploy with:
    #   kubectl get configmap -n otel-demo-research -l 'app.kubernetes.io/name=flagd'
    [string]$ConfigMapName = "flagd-config",
    [string]$ConfigMapKey = "demo.flagd.json",

    [int]$FlagdPropagationSeconds = 3,
    [switch]$SkipRestore
)

$ErrorActionPreference = "Stop"

# Pull in the shared kubectl helpers from the OB lib (read-only use; no edits).
Import-Module (Join-Path (Join-Path (Split-Path -Parent $PSScriptRoot) "lib") "ResearchLab.psm1") -Force

function Get-FlagdConfig {
    param(
        [Parameter(Mandatory = $true)][string]$Namespace,
        [Parameter(Mandatory = $true)][string]$ConfigMapName,
        [Parameter(Mandatory = $true)][string]$ConfigMapKey
    )
    $cm = Invoke-ResearchLabKubectlJson -ArgumentList @(
        "get", "configmap", $ConfigMapName, "-n", $Namespace, "-o", "json"
    )
    if (-not $cm.data) {
        throw "ConfigMap $Namespace/$ConfigMapName has no .data field"
    }
    $jsonText = $cm.data.$ConfigMapKey
    if (-not $jsonText) {
        throw "ConfigMap $Namespace/$ConfigMapName has no key '$ConfigMapKey'"
    }
    return @{
        configmap = $cm
        json_text = $jsonText
        parsed    = ($jsonText | ConvertFrom-Json -Depth 50)
    }
}

function Set-FlagVariant {
    param(
        [Parameter(Mandatory = $true)][object]$ParsedConfig,
        [Parameter(Mandatory = $true)][string]$FlagName,
        [Parameter(Mandatory = $true)][string]$Variant,
        [Parameter(Mandatory = $true)][string]$Namespace,
        [Parameter(Mandatory = $true)][string]$ConfigMapName,
        [Parameter(Mandatory = $true)][string]$ConfigMapKey
    )

    if (-not $ParsedConfig.flags.$FlagName) {
        throw "Flag '$FlagName' not found in flagd config"
    }

    $flagDef = $ParsedConfig.flags.$FlagName
    if (-not $flagDef.variants.$Variant -and $Variant -ne "off") {
        # "off" is the canonical safe restore target even if not explicitly listed
        $variantList = ($flagDef.variants.PSObject.Properties.Name) -join ", "
        throw "Flag '$FlagName' has no variant '$Variant'. Available: $variantList"
    }

    # Mutate the in-memory parsed object, then re-emit JSON.
    $flagDef.defaultVariant = $Variant

    $newJson = $ParsedConfig | ConvertTo-Json -Depth 50 -Compress:$false
    # ConvertTo-Json in PS5+ does not preserve insertion order for nested
    # objects perfectly, but flagd only reads the data, not its order.

    # Patch the ConfigMap. We use `kubectl patch` with strategic-merge so
    # other ConfigMap data keys are preserved.
    $patch = @{ data = @{ $ConfigMapKey = $newJson } } | ConvertTo-Json -Depth 50 -Compress
    Invoke-ResearchLabKubectlText -ArgumentList @(
        "patch", "configmap", $ConfigMapName,
        "-n", $Namespace,
        "--type=merge",
        "-p", $patch
    ) | Out-Host
}

# ---------------------------------------------------------------------------
# 1. Read current state — captures the original variant for restore.
# ---------------------------------------------------------------------------
Write-Host "Invoke-FlagdFlip: reading ConfigMap $Namespace/$ConfigMapName"
$state = Get-FlagdConfig -Namespace $Namespace -ConfigMapName $ConfigMapName -ConfigMapKey $ConfigMapKey

if (-not $state.parsed.flags.$FlagName) {
    throw "Flag '$FlagName' not present in $ConfigMapName/$ConfigMapKey"
}

$originalVariant = [string]$state.parsed.flags.$FlagName.defaultVariant
Write-Host "Invoke-FlagdFlip: flag='$FlagName' current_variant='$originalVariant' -> '$Variant'"

# ---------------------------------------------------------------------------
# 2. Set the new variant.
# ---------------------------------------------------------------------------
Set-FlagVariant `
    -ParsedConfig $state.parsed `
    -FlagName $FlagName `
    -Variant $Variant `
    -Namespace $Namespace `
    -ConfigMapName $ConfigMapName `
    -ConfigMapKey $ConfigMapKey

Write-Host "Invoke-FlagdFlip: flag flipped; settling $FlagdPropagationSeconds s for flagd to pick up"
Start-Sleep -Seconds $FlagdPropagationSeconds

# ---------------------------------------------------------------------------
# 3. Active-fault window.
# ---------------------------------------------------------------------------
Write-Host "Invoke-FlagdFlip: active-fault window $DurationSeconds s"
Start-Sleep -Seconds $DurationSeconds

# ---------------------------------------------------------------------------
# 4. Restore.
# ---------------------------------------------------------------------------
if ($SkipRestore) {
    Write-Warning "Invoke-FlagdFlip: SkipRestore set — flag '$FlagName' left at variant '$Variant'"
} else {
    Write-Host "Invoke-FlagdFlip: restoring flag '$FlagName' -> '$originalVariant'"
    # Re-read state in case anything else changed.
    $state = Get-FlagdConfig -Namespace $Namespace -ConfigMapName $ConfigMapName -ConfigMapKey $ConfigMapKey
    Set-FlagVariant `
        -ParsedConfig $state.parsed `
        -FlagName $FlagName `
        -Variant $originalVariant `
        -Namespace $Namespace `
        -ConfigMapName $ConfigMapName `
        -ConfigMapKey $ConfigMapKey
    Start-Sleep -Seconds $FlagdPropagationSeconds
}

# Return restore metadata to the caller for logging
[ordered]@{
    flag_name         = $FlagName
    variant_applied   = $Variant
    original_variant  = $originalVariant
    duration_seconds  = $DurationSeconds
    namespace         = $Namespace
    configmap_name    = $ConfigMapName
    restored          = (-not $SkipRestore)
} | ConvertTo-Json -Depth 5

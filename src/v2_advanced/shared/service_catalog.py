"""Service catalog loader.

Reads YAML catalogs from `deploy/research-lab/service-catalogs/` and turns
them into either:
  - a structured `ServiceCatalog` dataclass, OR
  - a rendered "CANONICAL SERVICES" prompt block compatible with the
    hardcoded block in `extractor.py` (used by the LLM extractor when
    operating on a non-OB app).

Isolation contract:
  This module is OPT-IN. Callers must explicitly pass a catalog path or
  set the `KG_SERVICE_CATALOG` env var. The default behavior of every
  caller is to use the existing hardcoded OB block — this loader is
  never consulted by default.

Usage:
    from v2_advanced.shared.service_catalog import (
        load_catalog, render_canonical_services_block, env_catalog_path,
    )

    catalog = load_catalog(Path("deploy/research-lab/service-catalogs/otel-demo.yaml"))
    block = render_canonical_services_block(catalog)
    # block is a string compatible with extractor.py prompt composition.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as e:
    raise ImportError(
        "PyYAML is required to load service catalogs. "
        "Install with: pip install pyyaml"
    ) from e


# Env var used by callers that want to opt-in to a catalog without changing
# their CLI args. The extractor checks this first; if set, builds the prompt
# block from the catalog at the env-var path.
ENV_SERVICE_CATALOG = "KG_SERVICE_CATALOG"


@dataclass(frozen=True)
class CanonicalService:
    name: str
    aliases: tuple[str, ...] = ()
    language: str = ""
    role: str = ""
    criticality: str = ""


@dataclass(frozen=True)
class ServiceCatalog:
    app_id: str
    display_name: str
    namespace: str
    canonical_services: tuple[CanonicalService, ...]
    canonical_components: tuple[str, ...]
    canonical_error_classes: dict[str, tuple[str, ...]]
    infra_components: tuple[dict[str, str], ...] = field(default_factory=tuple)

    @property
    def service_names(self) -> tuple[str, ...]:
        return tuple(s.name for s in self.canonical_services)


def env_catalog_path() -> Path | None:
    """Return the catalog path from the KG_SERVICE_CATALOG env var, or None."""
    p = os.environ.get(ENV_SERVICE_CATALOG)
    if not p:
        return None
    path = Path(p)
    if not path.exists():
        raise FileNotFoundError(
            f"{ENV_SERVICE_CATALOG}={p} but file does not exist"
        )
    return path


def load_catalog(path: Path | str) -> ServiceCatalog:
    """Load and validate a service catalog YAML file."""
    path = Path(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top-level YAML must be a mapping")

    # Required fields
    for required in ("app_id", "display_name", "namespace", "canonical_services",
                     "canonical_components", "canonical_error_classes"):
        if required not in data:
            raise ValueError(f"{path}: missing required field '{required}'")

    # Parse services
    services_raw = data["canonical_services"]
    if not isinstance(services_raw, list):
        raise ValueError(f"{path}: canonical_services must be a list")
    services: list[CanonicalService] = []
    for s in services_raw:
        if not isinstance(s, dict) or "name" not in s:
            raise ValueError(f"{path}: each canonical_services entry must be a mapping with 'name'")
        services.append(CanonicalService(
            name=str(s["name"]),
            aliases=tuple(str(a) for a in (s.get("aliases") or [])),
            language=str(s.get("language") or ""),
            role=str(s.get("role") or ""),
            criticality=str(s.get("criticality") or ""),
        ))

    # Parse error classes
    err_raw = data["canonical_error_classes"]
    if not isinstance(err_raw, dict):
        raise ValueError(f"{path}: canonical_error_classes must be a mapping")
    error_classes: dict[str, tuple[str, ...]] = {}
    for proto, lst in err_raw.items():
        if not isinstance(lst, list):
            raise ValueError(f"{path}: canonical_error_classes.{proto} must be a list")
        error_classes[str(proto)] = tuple(str(x) for x in lst)

    # Parse components
    components_raw = data["canonical_components"]
    if not isinstance(components_raw, list):
        raise ValueError(f"{path}: canonical_components must be a list")
    components = tuple(str(c) for c in components_raw)

    # Optional infra
    infra_raw = data.get("infra_components") or []
    if not isinstance(infra_raw, list):
        raise ValueError(f"{path}: infra_components must be a list when present")
    infra = tuple(dict(i) for i in infra_raw if isinstance(i, dict))

    return ServiceCatalog(
        app_id=str(data["app_id"]),
        display_name=str(data["display_name"]),
        namespace=str(data["namespace"]),
        canonical_services=tuple(services),
        canonical_components=components,
        canonical_error_classes=error_classes,
        infra_components=infra,
    )


def render_canonical_services_block(cat: ServiceCatalog) -> str:
    """Render the catalog into a canonical-services prompt block compatible
    with the hardcoded block in src/v2_advanced/proposal_d_knowledge_graph/extractor.py.

    This output is plugged into the TICKET and WINDOW system prompts at the
    point where the existing `_CANONICAL_SERVICES_BLOCK` would otherwise be
    interpolated.
    """
    lines: list[str] = []
    lines.append("CANONICAL SERVICE NAMES — use these EXACTLY, never paraphrase:")
    # Three-column grid for readability
    names = list(cat.service_names)
    for i in range(0, len(names), 3):
        row = names[i : i + 3]
        # Right-pad each name to 24 chars so columns align
        padded = "".join(f"  {n:<24}" for n in row).rstrip()
        lines.append(f"  {padded}".rstrip())
    lines.append("")
    lines.append("Normalization rules — apply these when extracting:")
    for svc in cat.canonical_services:
        if svc.aliases:
            alias_list = " / ".join(f'"{a}"' for a in svc.aliases)
            lines.append(f"  - {alias_list}  ->  {svc.name}")
    lines.append("")
    lines.append("If a service is mentioned but does NOT match any canonical name above")
    lines.append("(e.g. an external 3rd-party service), omit it — do not invent new names.")
    lines.append("")
    lines.append("CANONICAL COMPONENT NAMES (use exactly when present in the text):")
    # Wrap components to ~6 per row
    comps = list(cat.canonical_components)
    for i in range(0, len(comps), 6):
        row = comps[i : i + 6]
        lines.append("  " + ", ".join(row) + ("," if i + 6 < len(comps) else ""))
    lines.append("")
    lines.append("CANONICAL ERROR CLASSES (use exactly when matching):")
    for proto, errs in cat.canonical_error_classes.items():
        lines.append(f"  {proto.upper()}: " + ", ".join(errs))
    return "\n".join(lines)


def resolve_catalog(
    *, explicit_path: Path | str | None = None
) -> ServiceCatalog | None:
    """High-level helper for opt-in callers.

    Resolution order:
      1. `explicit_path` argument (highest priority).
      2. `KG_SERVICE_CATALOG` env var.
      3. None — caller falls back to its existing hardcoded default.

    Returns None when no catalog is requested. Callers MUST treat None as
    "use existing hardcoded default behavior" (preserves OB bit-identity).
    """
    if explicit_path is not None:
        return load_catalog(explicit_path)
    env_path = env_catalog_path()
    if env_path is not None:
        return load_catalog(env_path)
    return None

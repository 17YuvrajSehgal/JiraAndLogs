"""Shared resplit-manifest loader.

`make_resplit.py` writes a `triage-split-manifest-v2-resplit.json` with
a `window_assignment: {window_id → "train"|"validation"|"test"}` map.
When this file exists, the agent loaders should prefer its assignments
over the JSONL's baked-in `split` field — that's how OB has its
70/15/15 stratified split applied without rewriting the JSONL.

For OTel Demo we run `make_resplit.py` once to materialize the manifest;
the loader picks it up automatically.

Convention:
  - File at `<global_dir>/triage-split-manifest-v2-resplit.json`
  - Returns dict[window_id, split_name].
  - When the manifest is absent, returns None — loaders fall back to
    `window.get("split")` from the JSONL.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path


log = logging.getLogger(__name__)


_MANIFEST_FILENAME = "triage-split-manifest-v2-resplit.json"


def load_split_manifest(global_dir: Path) -> dict[str, str] | None:
    """Return window_id → split mapping from the v2-resplit manifest.

    Returns None when the manifest is missing — caller falls back to
    the JSONL's `split` field."""
    path = global_dir / _MANIFEST_FILENAME
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.warning("split manifest unreadable at %s: %s", path, e)
        return None
    assignment = data.get("window_assignment")
    if not isinstance(assignment, dict) or not assignment:
        log.warning("split manifest at %s has no window_assignment", path)
        return None
    log.info(
        "split manifest loaded: %d windows assigned (path=%s)",
        len(assignment), path,
    )
    return {str(k): str(v) for k, v in assignment.items()}


def resolve_split(
    window: dict,
    manifest: dict[str, str] | None,
) -> str:
    """Return the effective split for one window row.

    Manifest takes precedence when present; falls back to the row's
    own `split` field otherwise."""
    if manifest is not None:
        wid = window.get("window_id")
        if wid and wid in manifest:
            return manifest[wid]
    return str(window.get("split", ""))

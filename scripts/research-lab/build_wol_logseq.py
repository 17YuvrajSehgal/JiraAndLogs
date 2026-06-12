"""Build `v2_logseq/<window_id>.jsonl` files for the WoL Mode 3 dataset.

LogSeq2Vec's pipeline expects, per train/val/test window, a file with
one JSON line per log line, schema
    {"ts_ns": int, "service": str, "severity": str, "line": str}

For the synthetic dataset these come from raw Loki dumps. WoL has no
Loki — instead each WoL record carries a `log_quotes` list (the lines
the JIRA reporter pasted into the ticket), already mirrored into
`global-triage-examples.jsonl` as `triage_evidence_text`.

This adapter splits `triage_evidence_text` on newlines, applies the
same volatile-substring normaliser used by the synthetic data prep, and
writes one v2_logseq file per window. Memory side is not needed — the
LogSeq2Vec pipeline encodes memory tickets via the line-encoder's
single-line path using `build_memory_doc_text`.

Usage:
    PYTHONPATH=src python scripts/research-lab/build_wol_logseq.py \\
        --global-dir data/derived/global/2026-06-11-wol-real-global
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def _make_normalizer():
    from memorygraph.log_signatures import _TRACE_ID, _SPAN_ID, _UUID, _ISO_TS
    _IPV4 = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?::\d{1,5})?\b")
    _BIG_HEX = re.compile(r"\b[0-9a-f]{8,}\b")
    _BIG_NUM = re.compile(r"\b\d{6,}\b")

    def normalize(line: str) -> str:
        s = line
        s = _UUID.sub("<UUID>", s)
        s = _TRACE_ID.sub("<TRACE>", s)
        s = _SPAN_ID.sub("<SPAN>", s)
        s = _ISO_TS.sub("<TS>", s)
        s = _IPV4.sub("<IP>", s)
        s = _BIG_HEX.sub("<HEX>", s)
        s = _BIG_NUM.sub("<N>", s)
        return s

    return normalize


_SEV_TOKENS = {
    "error":   ("error", " err ", "exception", "failed", "failure", "fatal"),
    "warning": ("warn", "warning"),
}


def _infer_severity(line: str) -> str:
    low = line.lower()
    for sev, tokens in _SEV_TOKENS.items():
        if any(t in low for t in tokens):
            return sev
    return "info"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--global-dir", type=Path,
                    default=Path("data/derived/global/2026-06-11-wol-real-global"))
    ap.add_argument("--out-subdir", default="v2_logseq")
    ap.add_argument("--max-lines-per-window", type=int, default=80)
    args = ap.parse_args()

    import sys
    sys.path.insert(0, "src")

    out_root = args.global_dir / args.out_subdir
    out_root.mkdir(parents=True, exist_ok=True)

    examples_path = args.global_dir / "global-triage-examples.jsonl"
    normalize = _make_normalizer()

    n_windows = 0
    n_lines = 0
    n_skipped = 0

    with examples_path.open(encoding="utf-8") as fh:
        for raw in fh:
            d = json.loads(raw)
            wid = d.get("window_id") or ""
            evidence = (d.get("triage_evidence_text") or "").strip()
            if not wid or not evidence:
                n_skipped += 1
                continue
            service = d.get("scenario_family") or d.get("service_name") or "wol"
            lines_raw = [ln for ln in evidence.splitlines() if ln.strip()]
            lines_raw = lines_raw[: args.max_lines_per_window]
            out_path = out_root / f"{wid}.jsonl"
            with out_path.open("w", encoding="utf-8") as fout:
                for i, ln in enumerate(lines_raw):
                    fout.write(json.dumps({
                        "ts_ns":    i,
                        "service":  service,
                        "severity": _infer_severity(ln),
                        "line":     normalize(ln)[:240],
                    }) + "\n")
            n_windows += 1
            n_lines += len(lines_raw)

    print(f"[wol-logseq] wrote {n_windows} v2_logseq files "
          f"({n_lines} total lines, {n_skipped} skipped) -> {out_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

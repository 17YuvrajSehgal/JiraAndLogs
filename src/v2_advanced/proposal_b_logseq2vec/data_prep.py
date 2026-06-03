"""Parse raw Loki JSON dumps into per-window log-line sequences.

Each window has a `<window_id>.json` file with a `response.data.result`
array of "streams". Each stream is one Kubernetes pod / service, and
has a list of (timestamp_ns, log_line) pairs.

We produce, per window, a flat sorted-by-timestamp list of log lines,
keeping only the most useful ones (errors/warnings if abundant; sampled
info lines otherwise). Each line is templated via the existing
log_signatures regex set so volatile bits (trace IDs, hashes) are
stripped.

Output:
    data/derived/global/<id>/v2_logseq/<window_id>.jsonl
        one JSON-line per log line:
            {"ts": "...", "service": "...", "severity": "...", "line": "..."}
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from v2_advanced.shared import get_logger, log_step

log = get_logger("phase_b.data_prep")


# Reuse the existing volatile-substring strippers from log_signatures.
# (Imported lazily inside the function so importing this module doesn't
# require the full memorygraph stack.)
def _make_normalizer():
    from memorygraph.log_signatures import (
        _TRACE_ID, _SPAN_ID, _UUID, _ISO_TS,
    )
    # Plus a few generic patterns
    _IPV4 = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?::\d{1,5})?\b")
    _BIG_HEX = re.compile(r"\b[0-9a-f]{8,}\b")
    _BIG_NUM = re.compile(r"\b\d{6,}\b")
    _PODSUFFIX = re.compile(r"-[a-f0-9]{7,}-[a-z0-9]{5}\b")

    def normalize(line: str) -> str:
        s = line
        s = _UUID.sub("<UUID>", s)
        s = _TRACE_ID.sub("<TRACE>", s)
        s = _SPAN_ID.sub("<SPAN>", s)
        s = _ISO_TS.sub("<TS>", s)
        s = _IPV4.sub("<IP>", s)
        s = _PODSUFFIX.sub("-<HASH>-<ID>", s)
        s = _BIG_HEX.sub("<HEX>", s)
        s = _BIG_NUM.sub("<N>", s)
        return s
    return normalize


def _extract_lines_from_loki_json(loki_path: Path) -> list[dict]:
    """Parse one Loki dump file and return a list of normalized log
    lines with their metadata."""
    normalize = _make_normalizer()
    try:
        d = json.loads(loki_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    streams = d.get("service_window", {}).get("response", {}).get("data", {}).get("result", [])
    out = []
    for stream in streams:
        meta = stream.get("stream", {})
        service = meta.get("service_name") or meta.get("app") or "?"
        severity = meta.get("detected_level") or meta.get("severity") or "info"
        for entry in stream.get("values", []):
            if len(entry) < 2:
                continue
            ts_ns, line = entry[0], entry[1]
            # Loki lines are often JSON-structured. Pull the message field
            # if present, otherwise use the whole raw line.
            text = line
            try:
                inner = json.loads(line)
                if isinstance(inner, dict):
                    text = inner.get("message", line)
            except (json.JSONDecodeError, ValueError):
                pass
            normalized = normalize(str(text))[:240]   # bound length
            out.append({
                "ts_ns": int(ts_ns) if ts_ns.isdigit() else 0,
                "service": service,
                "severity": severity.lower(),
                "line": normalized,
            })
    out.sort(key=lambda r: r["ts_ns"])
    return out


def gather_per_window(loki_root: Path, *, max_lines: int = 100) -> dict[str, list[dict]]:
    """Walk a Loki dir, find all <window_id>.json files, parse each.

    Returns dict {window_id: list_of_lines}.

    Pre-filter: keep all error/warn lines, then sample info lines down to
    fit `max_lines` total.
    """
    out = {}
    for jf in sorted(loki_root.glob("*.json")):
        window_id = jf.stem
        lines = _extract_lines_from_loki_json(jf)
        if not lines:
            continue
        errs = [l for l in lines if l["severity"] in {"error", "err", "warn", "warning", "fatal"}]
        infos = [l for l in lines if l not in errs]
        # Aggregate per window: at most max_lines total. Prefer errors.
        keep = errs[:max_lines]
        slots_left = max(0, max_lines - len(keep))
        if slots_left > 0 and infos:
            # Stride-sample the info lines
            stride = max(1, len(infos) // slots_left)
            keep += infos[::stride][:slots_left]
        keep.sort(key=lambda r: r["ts_ns"])
        out[window_id] = keep
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--global-dir", type=Path, required=True)
    p.add_argument("--runs-root", type=Path, required=True,
                   help="root containing all dataset runs (data/runs)")
    p.add_argument("--out-subdir", default="v2_logseq")
    p.add_argument("--max-lines-per-window", type=int, default=100)
    args = p.parse_args()

    out_root = args.global_dir / args.out_subdir
    out_root.mkdir(parents=True, exist_ok=True)

    n_windows = 0
    n_lines = 0

    with log_step(log, "scan_runs", root=str(args.runs_root)):
        run_dirs = sorted(d for d in args.runs_root.iterdir() if d.is_dir())
        log.info("found runs", n=len(run_dirs))

    for rd in run_dirs:
        loki_dir = rd / "raw" / "loki"
        if not loki_dir.exists():
            continue
        per_window = gather_per_window(loki_dir, max_lines=args.max_lines_per_window)
        for wid, lines in per_window.items():
            out_path = out_root / f"{wid}.jsonl"
            with out_path.open("w", encoding="utf-8") as fh:
                for l in lines:
                    fh.write(json.dumps(l) + "\n")
            n_windows += 1
            n_lines += len(lines)
        if n_windows % 100 == 0:
            log.info("progress", n_windows=n_windows, n_lines=n_lines)

    log.info("done", n_windows=n_windows, total_lines=n_lines, out_root=str(out_root))


if __name__ == "__main__":
    main()

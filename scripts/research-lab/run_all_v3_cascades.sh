#!/usr/bin/env bash
# Run all five WoL v3 cascade pipelines in parallel against the v3 dataset,
# then aggregate the results into a single summary in one place.
#
# THIS IS A FULL-RUN ORCHESTRATOR — NOT A SMOKE RUN.
#
# Each pipeline script (run_*_wol_mode3.py) calls .train_and_predict() over the
# entire v3 dataset:
#   - memory: all 38,587 cached KG-extracted memory tickets
#   - queries: the full 13,388-window test split (Kafka + MariaDB families)
#   - both match relations (coarse + strong)
#   - per-project stratification
# Verified 2026-06-23: none of the cascade scripts accept a --smoke or --limit
# flag, and the orchestrator does not pass anything that would subset the data.
#
# All five pipelines (BiEncoder, BM25, Hybrid-RRF, KG-retrieval, LogSeq2Vec)
# are independent — each fine-tunes any models it needs internally and reads
# only from the global-dir, never from another cascade's output. Therefore
# they can all run in parallel.
#
# Per-pipeline logs land under logs/v3_<pipeline>.log so you can `tail -f`
# any one of them independently. After all pipelines finish, the orchestrator
# aggregates every *-mode3-results.json into:
#   <out>/SUMMARY.md           — human-readable headline table for paper / review
#   <out>/v3-all-results.json  — machine-readable union of every pipeline's results
# Plus a printed table to the terminal.
#
# Usage:
#   bash scripts/research-lab/run_all_v3_cascades.sh
#
# Optional env overrides (sensible defaults baked in):
#   V3_GLOBAL_DIR  — where the v3 dataset lives
#   V3_OUT_DIR     — where prediction JSONLs + per-pipeline results land
#   HUMANIZED_SUB  — humanized timeline subdir (CRITICAL: must be v3's bulk-20260617)
#   SKIP_KG        — set to 1 to skip KG-retrieval (e.g. if KG extractions are stale)
#
# Each pipeline writes:
#   <out>/<name>-predictions.jsonl     — per-window prediction records
#   <out>/<name>-mode3-results.json    — headline Hit@K metrics
#
# To inspect live progress for one pipeline:
#   tail -f logs/v3_biencoder.log
#   tail -f logs/v3_bm25.log
#   tail -f logs/v3_hybrid_rrf.log
#   tail -f logs/v3_kg_retrieval.log
#   tail -f logs/v3_logseq2vec.log
#
# Or watch them all at once:
#   tail -f logs/v3_*.log

set -u    # error on undefined vars; intentionally NOT -e so one pipeline
          # failure doesn't kill the others — each runs independently.

# ---------- Configuration ----------
V3_GLOBAL_DIR="${V3_GLOBAL_DIR:-data/derived/global/2026-06-17-wol-real-v3-global}"
V3_OUT_DIR="${V3_OUT_DIR:-${V3_GLOBAL_DIR}/tch-lite-refit}"
HUMANIZED_SUB="${HUMANIZED_SUB:-bulk-20260617}"   # v3-specific — v2 was bulk-20260611
SKIP_KG="${SKIP_KG:-0}"

LOG_DIR="logs"
mkdir -p "$LOG_DIR" "$V3_OUT_DIR"

# ---------- Preflight checks ----------
echo "=== WoL v3 cascade orchestrator (FULL RUN — NOT SMOKE) ==="
echo "global-dir:        $V3_GLOBAL_DIR"
echo "out-dir:           $V3_OUT_DIR"
echo "humanized-subdir:  $HUMANIZED_SUB"
echo

required_files=(
    "$V3_GLOBAL_DIR/jira-memory-corpus.jsonl"
    "$V3_GLOBAL_DIR/global-triage-examples.jsonl"
    "$V3_GLOBAL_DIR/window-memory-matchings.jsonl"
    "$V3_GLOBAL_DIR/window-memory-matchings-strong.jsonl"
    "$V3_GLOBAL_DIR/triage-split-manifest.json"
    "$V3_GLOBAL_DIR/jira-shadow-humanized-v2/$HUMANIZED_SUB/timeline.jsonl"
)
for f in "${required_files[@]}"; do
    if [[ ! -f "$f" ]]; then
        echo "MISSING required file: $f" >&2
        echo "Aborting before any pipeline launches." >&2
        exit 1
    fi
done

kg_files=(
    "$V3_GLOBAL_DIR/v2_kg_extractions/all_extractions.jsonl"
    "$V3_GLOBAL_DIR/v2_kg_extractions_windows/all_extractions.jsonl"
)
kg_ok=1
for f in "${kg_files[@]}"; do
    if [[ ! -f "$f" ]]; then
        echo "KG extraction missing: $f" >&2
        kg_ok=0
    fi
done

if [[ "$kg_ok" == "0" ]] && [[ "$SKIP_KG" != "1" ]]; then
    echo "Hint: re-run KG extraction or set SKIP_KG=1 to skip KG-retrieval." >&2
    exit 1
fi

echo "Preflight checks passed."
echo

# ---------- Common args ----------
common_args=(
    --global-dir "$V3_GLOBAL_DIR"
    --out-dir "$V3_OUT_DIR"
)
# Most cascades accept --humanized-subdir; BM25 does not.
hum_args=(
    --humanized-subdir "$HUMANIZED_SUB"
)

export PYTHONPATH="${PYTHONPATH:-}:src"
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1

# ---------- Launch each pipeline in the background ----------
START_TS=$(date +%s)
echo "Launched at: $(date -u +'%Y-%m-%dT%H:%M:%SZ')"
echo

declare -A pids

echo "[launch] BiEncoder            -> $LOG_DIR/v3_biencoder.log"
python scripts/research-lab/run_biencoder_wol_mode3.py \
    "${common_args[@]}" "${hum_args[@]}" \
    > "$LOG_DIR/v3_biencoder.log" 2>&1 &
pids[biencoder]=$!

echo "[launch] BM25                 -> $LOG_DIR/v3_bm25.log"
python scripts/research-lab/run_bm25_wol_mode3.py \
    "${common_args[@]}" \
    > "$LOG_DIR/v3_bm25.log" 2>&1 &
pids[bm25]=$!

echo "[launch] Hybrid-RRF           -> $LOG_DIR/v3_hybrid_rrf.log"
python scripts/research-lab/run_hybrid_rrf_wol_mode3.py \
    "${common_args[@]}" "${hum_args[@]}" \
    > "$LOG_DIR/v3_hybrid_rrf.log" 2>&1 &
pids[hybrid_rrf]=$!

if [[ "$kg_ok" == "1" ]]; then
    echo "[launch] KG-retrieval         -> $LOG_DIR/v3_kg_retrieval.log"
    python scripts/research-lab/run_kg_retrieval_wol_mode3.py \
        "${common_args[@]}" "${hum_args[@]}" \
        > "$LOG_DIR/v3_kg_retrieval.log" 2>&1 &
    pids[kg_retrieval]=$!
else
    echo "[skip]   KG-retrieval (SKIP_KG=1 or extractions missing)"
fi

# LogSeq2Vec is INAPPLICABLE TO WoL — it requires per-window log-sequence files
# generated from raw Loki JSON via the `data_prep` step, which WoL doesn't have
# (WoL is text-only Jira tickets with no telemetry). The previous v2 cascade
# panel also omitted it for this reason; the WoL paper sets it aside.
# Re-enable only if you build per-window log-sequence files from triage_evidence_text.
echo "[skip]   LogSeq2Vec (not applicable to WoL — needs per-window Loki dumps)"

echo
echo "All pipelines launched. PIDs:"
for k in "${!pids[@]}"; do
    echo "  $k: ${pids[$k]}"
done
echo
echo "Tail any pipeline live:    tail -f $LOG_DIR/v3_<name>.log"
echo "Tail all at once:          tail -f $LOG_DIR/v3_*.log"
echo

# ---------- Wait + report ----------
echo "=== Waiting for all pipelines to finish ==="
declare -A status
for k in "${!pids[@]}"; do
    pid=${pids[$k]}
    if wait "$pid"; then
        status[$k]="OK"
    else
        status[$k]="FAILED (exit $?)"
    fi
    elapsed_min=$(( ($(date +%s) - START_TS) / 60 ))
    echo "[${elapsed_min}min] $k: ${status[$k]}"
done

# ---------- Per-pipeline status summary ----------
END_TS=$(date +%s)
TOTAL_MIN=$(( (END_TS - START_TS) / 60 ))
echo
echo "=== Cascade run complete ==="
echo "Total wall-clock: ${TOTAL_MIN} min"
echo
echo "Per-pipeline status:"
for k in "${!status[@]}"; do
    echo "  $k: ${status[$k]}"
done
echo
echo "=== Output files written ==="
for name in biencoder bm25 hybrid-rrf kg-retrieval logseq2vec; do
    pred="$V3_OUT_DIR/${name}-predictions.jsonl"
    if [[ -f "$pred" ]]; then
        n=$(wc -l < "$pred")
        echo "  ${name}-predictions.jsonl: $n rows"
    else
        echo "  ${name}-predictions.jsonl: MISSING"
    fi
done

# ---------- Aggregate per-pipeline results into ONE place ----------
echo
echo "=== Aggregating per-pipeline results -> $V3_OUT_DIR/SUMMARY.md ==="

# We delegate the aggregation to a small Python block — it cleanly handles
# missing files (failed pipelines), produces a Markdown table for the paper,
# a JSON union for machine consumption, and a terminal-friendly table.
V3_GLOBAL_DIR_ARG="$V3_GLOBAL_DIR" \
V3_OUT_DIR_ARG="$V3_OUT_DIR" \
TOTAL_MIN_ARG="$TOTAL_MIN" \
python - <<'PYEOF'
import json
import os
from pathlib import Path

global_dir = Path(os.environ["V3_GLOBAL_DIR_ARG"])
out_dir    = Path(os.environ["V3_OUT_DIR_ARG"])
total_min  = int(os.environ["TOTAL_MIN_ARG"])

pipelines = [
    ("biencoder",    "BiEncoder"),
    ("bm25",         "BM25"),
    ("hybrid-rrf",   "Hybrid-RRF"),
    ("kg-retrieval", "KG-Retrieval"),
    # LogSeq2Vec omitted — not applicable to WoL (no per-window log sequences).
]

results = {}
for slug, _name in pipelines:
    p = out_dir / f"{slug}-mode3-results.json"
    if p.exists():
        try:
            results[slug] = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            results[slug] = {"error": "malformed-json"}
    else:
        results[slug] = None

# ---- Markdown summary table ----
lines = []
lines.append(f"# WoL v3 Cascade Results — {global_dir.name}")
lines.append("")
lines.append(f"Generated by `run_all_v3_cascades.sh`. Total wall-clock: **{total_min} min**.")
lines.append("")
lines.append("**FULL RUN** — all five pipelines processed the entire v3 test split"
             " (Kafka + MariaDB families, 13,388 windows). Not a smoke run.")
lines.append("")
lines.append("## Headline metrics — coarse match")
lines.append("")
lines.append("| Pipeline      | n_with_gold | Hit@1   | Hit@5   | MRR     |")
lines.append("|---------------|------------:|--------:|--------:|--------:|")
for slug, name in pipelines:
    r = results.get(slug)
    if r is None:
        lines.append(f"| {name:<13} | (missing)   |       — |       — |       — |")
        continue
    if "error" in r:
        lines.append(f"| {name:<13} | ({r['error']})   |       — |       — |       — |")
        continue
    c = r.get("coarse", {})
    lines.append(
        f"| {name:<13} | {c.get('n_with_gold',0):>11d} | "
        f"{c.get('hit_at_1',0):>7.4f} | {c.get('hit_at_5',0):>7.4f} | {c.get('mrr',0):>7.4f} |"
    )
lines.append("")
lines.append("## Headline metrics — strong match (Jaccard > 0.15)")
lines.append("")
lines.append("| Pipeline      | n_with_gold | Hit@1   | Hit@5   | MRR     |")
lines.append("|---------------|------------:|--------:|--------:|--------:|")
for slug, name in pipelines:
    r = results.get(slug)
    if r is None or "error" in r:
        lines.append(f"| {name:<13} | —           |       — |       — |       — |")
        continue
    s = r.get("strong", {})
    lines.append(
        f"| {name:<13} | {s.get('n_with_gold',0):>11d} | "
        f"{s.get('hit_at_1',0):>7.4f} | {s.get('hit_at_5',0):>7.4f} | {s.get('mrr',0):>7.4f} |"
    )
lines.append("")

# Per-pipeline timing
lines.append("## Per-pipeline wall-clock")
lines.append("")
lines.append("| Pipeline | fit (s) | predict (s) | total (s) |")
lines.append("|----------|--------:|------------:|----------:|")
for slug, name in pipelines:
    r = results.get(slug)
    if r is None or "error" in r:
        lines.append(f"| {name:<13} | — | — | — |")
        continue
    md = r.get("metadata", {})
    fit  = md.get("fit_seconds")
    pred = md.get("predict_seconds")
    wall = md.get("wall_seconds")
    fit_s  = f"{fit:.1f}"  if isinstance(fit, (int, float))  else "—"
    pred_s = f"{pred:.1f}" if isinstance(pred,(int, float))  else "—"
    wall_s = f"{wall:.1f}" if isinstance(wall,(int, float))  else "—"
    lines.append(f"| {name:<13} | {fit_s:>7s} | {pred_s:>11s} | {wall_s:>9s} |")
lines.append("")

# Per-project Hit@5 under coarse match — for ANY pipeline that has it
projects_seen = set()
for slug, _ in pipelines:
    r = results.get(slug)
    if r is None or "error" in r: continue
    projects_seen.update((r.get("coarse") or {}).get("per_project", {}).keys())

if projects_seen:
    lines.append("## Per-project Hit@5 — coarse match")
    lines.append("")
    header = "| Project " + "".join(f"| {name:>13} " for _, name in pipelines) + "|"
    sep    = "|---------" + "".join("|" + "-"*15 for _ in pipelines) + "|"
    lines.append(header)
    lines.append(sep)
    for proj in sorted(projects_seen):
        row = [f"| {proj:<8}"]
        for slug, _ in pipelines:
            r = results.get(slug)
            if r is None or "error" in r:
                row.append(f"| {'—':>13}")
                continue
            v = (r.get("coarse") or {}).get("per_project", {}).get(proj)
            if v is None:
                row.append(f"| {'—':>13}")
            else:
                row.append(f"| {v.get('hit_at_5',0):>13.4f}")
        lines.append("".join(row) + " |")
    lines.append("")

lines.append("## How to reproduce")
lines.append("")
lines.append("```bash")
lines.append("bash scripts/research-lab/run_all_v3_cascades.sh")
lines.append("```")
lines.append("")
lines.append("Per-pipeline source-of-truth files (all in this directory):")
lines.append("")
for slug, name in pipelines:
    lines.append(f"- `{slug}-predictions.jsonl` + `{slug}-mode3-results.json` — {name}")
lines.append("")

# ---- Write SUMMARY.md ----
md_path = out_dir / "SUMMARY.md"
md_path.write_text("\n".join(lines), encoding="utf-8")
print(f"Wrote {md_path}")

# ---- Write v3-all-results.json (machine-readable union) ----
union = {
    "global_dataset_id": global_dir.name,
    "out_dir":           str(out_dir),
    "total_wall_minutes": total_min,
    "pipelines": {slug: results.get(slug) for slug, _ in pipelines},
}
json_path = out_dir / "v3-all-results.json"
json_path.write_text(json.dumps(union, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"Wrote {json_path}")

# ---- Print a terminal-friendly table (ASCII only — bash on Windows
# misrenders em-dashes from cp1252). The Markdown file keeps em-dashes.
print()
print("=" * 78)
print(f"{'Pipeline':<13} | {'coarse-Hit@1':>13} | {'coarse-Hit@5':>13} | {'coarse-MRR':>13}")
print("-" * 78)
for slug, name in pipelines:
    r = results.get(slug)
    if r is None or "error" in r:
        print(f"{name:<13} | {'-':>13} | {'-':>13} | {'-':>13}")
        continue
    c = r.get("coarse", {})
    print(f"{name:<13} | {c.get('hit_at_1',0):>13.4f} | "
          f"{c.get('hit_at_5',0):>13.4f} | {c.get('mrr',0):>13.4f}")
print("=" * 78)
PYEOF

echo
echo "=== All v3 results consolidated ==="
echo "Markdown summary:  $V3_OUT_DIR/SUMMARY.md"
echo "Machine-readable:  $V3_OUT_DIR/v3-all-results.json"
echo

# ---------- Exit code propagation ----------
# Exit nonzero if any pipeline failed.
for k in "${!status[@]}"; do
    if [[ "${status[$k]}" != "OK" ]]; then
        echo "WARN: at least one pipeline failed; see $LOG_DIR/v3_*.log for details." >&2
        exit 1
    fi
done
echo "All cascades succeeded. Next: scripts/agent/smoke_wol.py for the agent eval."

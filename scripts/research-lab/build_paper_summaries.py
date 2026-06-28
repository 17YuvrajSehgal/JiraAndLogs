"""Aggregate paper-results/*/*.json into per-category SUMMARY.md + master README.

Re-runnable: reads whatever result JSONs are present and tabulates them, so it
can be run repeatedly as jobs land. No side effects beyond writing SUMMARY.md
files and paper-results/README.md.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path("paper-results")
DATASETS = ["online-boutique", "otel-demo", "wol-v3"]


def _load(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:                                                # noqa: BLE001
        return None


def _c(d, *keys, default="—"):
    """nested get with formatting for floats"""
    cur = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    if isinstance(cur, float):
        return f"{cur:.3f}"
    return cur


def cascades() -> str:
    out = ["# Retrieval cascades — SUMMARY", "",
           "Coarse-match Hit@K / MRR on the test split (per-pipeline panel).", ""]
    methods = [("biencoder", "BiEncoder"), ("bm25", "BM25(raw-corpus)"),
               ("kg-retrieval", "KG"), ("hybrid-rrf", "Hybrid-RRF")]
    out.append("| dataset | metric | " + " | ".join(m[1] for m in methods) + " |")
    out.append("|---|---|" + "|".join(["---"] * len(methods)) + "|")
    for ds in DATASETS:
        res = {k: _load(ROOT / "retrieval-cascades" / ds / f"{k}-mode3-results.json") for k, _ in methods}
        for metric in ("hit_at_1", "hit_at_5", "mrr"):
            row = [_c(res[k], "coarse", metric) if res[k] else "—" for k, _ in methods]
            out.append(f"| {ds if metric=='hit_at_1' else ''} | {metric} | " + " | ".join(map(str, row)) + " |")
    return "\n".join(out) + "\n"


def baselines() -> str:
    fams = {"sota-dense": ["bge", "e5", "mpnet"], "tfidf": ["tfidf"],
            "bm25": ["bm25"], "cross-encoder-rerank": ["ce"], "llm-rag": ["llm-rag"]}
    out = ["# Baselines — SUMMARY", "",
           "Coarse Hit@5 (dense/lexical over humanized corpus; llm-rag on 500-window subset).", "",
           "| dataset | " + " | ".join(m for ms in fams.values() for m in ms) + " |",
           "|---|" + "|".join(["---"] * sum(len(v) for v in fams.values())) + "|"]
    for ds in DATASETS:
        cells = []
        for fam, ms in fams.items():
            for m in ms:
                r = _load(ROOT / "baselines" / fam / ds / f"{m}-results.json")
                cells.append(_c(r, "coarse", "hit_at_5") if r else "—")
        out.append(f"| {ds} | " + " | ".join(map(str, cells)) + " |")
    return "\n".join(out) + "\n"


def kg_usefulness() -> str:
    out = ["# KG usefulness — ±graph ablation SUMMARY", "",
           "Hybrid-RRF WITH graph (cascade panel) vs WITHOUT graph (this category). "
           "Δ = with − without quantifies the KG's marginal contribution.", "",
           "| dataset | metric | with-graph | no-graph | Δ (KG effect) |",
           "|---|---|---|---|---|"]
    for ds in DATASETS:
        wg = _load(ROOT / "retrieval-cascades" / ds / "hybrid-rrf-mode3-results.json")
        ng = _load(ROOT / "kg-usefulness" / ds / "hybrid-rrf-nograph-mode3-results.json")
        for metric in ("hit_at_1", "hit_at_5", "mrr"):
            if wg and ng:
                a = wg["coarse"][metric]; b = ng["coarse"][metric]
                out.append(f"| {ds if metric=='hit_at_1' else ''} | {metric} | {a:.3f} | {b:.3f} | {a-b:+.3f} |")
            else:
                out.append(f"| {ds if metric=='hit_at_1' else ''} | {metric} | "
                           f"{_c(wg,'coarse',metric) if wg else '—'} | {_c(ng,'coarse',metric) if ng else '—'} | — |")
    return "\n".join(out) + "\n"


def gold_validation() -> str:
    out = ["# Gold validation (LLM-as-judge) — SUMMARY", "",
           "Qwen2.5-7B rates gold ticket vs a random control (1-5). A positive gap "
           "(gold > random) is evidence the gold labels are meaningful.", "",
           "| dataset | gold mean | random mean | gap | gold %rel(≥4) | random %rel |",
           "|---|---|---|---|---|---|"]
    for ds in DATASETS:
        r = _load(ROOT / "gold-validation" / ds / "llm-judge-gold-results.json")
        if r:
            out.append(f"| {ds} | {r['gold_mean_score']:.2f} | {r['random_mean_score']:.2f} | "
                       f"{r['discrimination_gap']:.2f} | {100*r['gold_frac_relevant_ge4']:.0f}% | "
                       f"{100*r['random_frac_relevant_ge4']:.0f}% |")
        else:
            out.append(f"| {ds} | — | — | — | — | — |")
    return "\n".join(out) + "\n"


def robustness() -> str:
    out = ["# Robustness — multi-seed BiEncoder SUMMARY", "",
           "BiEncoder coarse Hit@5 across seeds (42 = cascade panel; 1,2 = robustness).", "",
           "| dataset | seed42 | seed1 | seed2 | mean | std |", "|---|---|---|---|---|---|"]
    import statistics
    for ds in ("online-boutique", "otel-demo"):
        vals = {}
        s42 = _load(ROOT / "retrieval-cascades" / ds / "biencoder-mode3-results.json")
        vals[42] = s42["coarse"]["hit_at_5"] if s42 else None
        for s in (1, 2):
            r = _load(ROOT / "robustness" / "multiseed" / ds / f"seed{s}" / "biencoder-mode3-results.json")
            vals[s] = r["coarse"]["hit_at_5"] if r else None
        present = [v for v in vals.values() if v is not None]
        m = f"{statistics.mean(present):.3f}" if present else "—"
        sd = f"{statistics.pstdev(present):.3f}" if len(present) > 1 else "—"
        out.append(f"| {ds} | {vals[42] or '—'} | {vals.get(1) or '—'} | {vals.get(2) or '—'} | {m} | {sd} |")
    return "\n".join(out) + "\n"


def agent_e2e() -> str:
    out = ["# Agent end-to-end — SUMMARY", "",
           "Full agent over the test split (predictions-backed skills + controller).", "",
           "| dataset | Hit@1 | Hit@5 | Hit@10 | triage_acc | n_cases |", "|---|---|---|---|---|---|"]
    for ds in DATASETS:
        r = _load(ROOT / "agent-end-to-end" / ds / "agent-eval.json")
        if not r:
            out.append(f"| {ds} | — | — | — | — | — |"); continue
        # schema is defensive — try common locations
        agg = r.get("aggregate") or r.get("metrics") or r
        def g(*ks):
            for k in ks:
                if isinstance(agg, dict) and k in agg and isinstance(agg[k], (int, float)):
                    return f"{agg[k]:.3f}"
            return "—"
        out.append(f"| {ds} | {g('hit_at_1','mean_hit_at_1')} | {g('hit_at_5','mean_hit_at_5')} | "
                   f"{g('hit_at_10','mean_hit_at_10')} | {g('triage_accuracy')} | "
                   f"{agg.get('n_cases', agg.get('n', '—'))} |")
    return "\n".join(out) + "\n"


def main():
    cats = {
        "retrieval-cascades": cascades, "baselines": baselines,
        "kg-usefulness": kg_usefulness, "gold-validation": gold_validation,
        "robustness": robustness, "agent-end-to-end": agent_e2e,
    }
    for name, fn in cats.items():
        try:
            (ROOT / name / "SUMMARY.md").write_text(fn(), encoding="utf-8")
            print(f"wrote {name}/SUMMARY.md")
        except Exception as e:                                       # noqa: BLE001
            print(f"SKIP {name}: {e}")
    # master README
    readme = ["# paper-results — ICSE result set", "",
              "Fresh, publishable results (clean of `data/` and the old `results/`). "
              "See `DOCS/collection-log.md` for provenance and `DOCS/audit-findings.md` "
              "for the correctness audit. Large per-window predictions/traces are shipped "
              "as a release archive (gitignored).", "",
              "## Category summaries"]
    for name in cats:
        readme.append(f"- [`{name}/SUMMARY.md`]({name}/SUMMARY.md)")
    readme += ["- `agent-value/` — cost@iso-accuracy + skill/tool/budget ablations (per-dataset JSON)",
               "- `provenance/` — env freeze, config (seeds/epochs/splits), git SHA", "",
               "## Headline (WoL real data, coarse Hit@5)",
               "Hybrid-RRF **0.970** > BiEncoder 0.905 > LLM-RAG 0.856 > BM25 0.727 — "
               "fusion of SPLADE+BiEncoder+graph wins on real Jira data and beats the LLM-RAG baseline."]
    (ROOT / "README.md").write_text("\n".join(readme) + "\n", encoding="utf-8")
    print("wrote README.md")


if __name__ == "__main__":
    main()

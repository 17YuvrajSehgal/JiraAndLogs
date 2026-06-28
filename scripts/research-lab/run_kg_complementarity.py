"""KG complementarity analysis (KG-usefulness angle 2).

Quantifies what the graph retriever contributes that dense (BiEncoder) and
sparse (BM25) miss: per window-with-gold, compute Hit@5 for each retriever, then
report how often the KG is correct where BiEncoder is wrong (the graph's UNIQUE
contribution), and the union coverage. Reads the on-disk cascade prediction
JSONLs; no GPU. Writes paper-results/kg-usefulness/complementarity.md.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path("paper-results")
DATASETS = ["online-boutique", "otel-demo", "wol-v3"]
K = 5


def hits(path: Path) -> dict[str, int]:
    out = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        gold = set(d.get("gold_matched_issue_ids") or [])
        if not gold:
            continue
        top = list(d.get("matched_issue_ids") or [])[:K]
        out[d["window_id"]] = int(any(t in gold for t in top))
    return out


def main():
    rows = []
    for ds in DATASETS:
        be = hits(ROOT / "retrieval-cascades" / ds / "biencoder-predictions.jsonl")
        kg = hits(ROOT / "retrieval-cascades" / ds / "kg-retrieval-predictions.jsonl")
        bm = hits(ROOT / "retrieval-cascades" / ds / "bm25-predictions.jsonl")
        keys = sorted(set(be) & set(kg) & set(bm))
        if not keys:
            rows.append((ds, None)); continue
        n = len(keys)
        kg_only = sum(1 for k in keys if kg[k] and not be[k])          # graph correct, dense wrong
        be_only = sum(1 for k in keys if be[k] and not kg[k])
        kg_uniq_all = sum(1 for k in keys if kg[k] and not be[k] and not bm[k])  # only graph
        union = sum(1 for k in keys if be[k] or kg[k] or bm[k])
        rows.append((ds, {
            "n": n,
            "biencoder_hit5": sum(be[k] for k in keys) / n,
            "kg_hit5": sum(kg[k] for k in keys) / n,
            "bm25_hit5": sum(bm[k] for k in keys) / n,
            "kg_correct_dense_wrong_pct": 100 * kg_only / n,
            "dense_correct_kg_wrong_pct": 100 * be_only / n,
            "kg_unique_vs_both_pct": 100 * kg_uniq_all / n,
            "union_coverage_hit5": union / n,
        }))

    md = ["# KG complementarity (angle 2) — unique-hit analysis", "",
          f"Per window-with-gold (shared across retrievers), Hit@{K}. "
          "'KG correct/dense wrong' = windows the graph gets right that the "
          "BiEncoder misses (the graph's marginal recall); 'KG unique vs both' = "
          "only the graph is correct (neither dense nor sparse).", "",
          "| dataset | n | BiEncoder | KG | BM25 | KG✓&dense✗ | dense✓&KG✗ | KG-only(vs both) | union |",
          "|---|---|---|---|---|---|---|---|---|"]
    for ds, r in rows:
        if r is None:
            md.append(f"| {ds} | — (preds missing) |||||||| "); continue
        md.append(f"| {ds} | {r['n']} | {r['biencoder_hit5']:.3f} | {r['kg_hit5']:.3f} | "
                  f"{r['bm25_hit5']:.3f} | {r['kg_correct_dense_wrong_pct']:.1f}% | "
                  f"{r['dense_correct_kg_wrong_pct']:.1f}% | {r['kg_unique_vs_both_pct']:.1f}% | "
                  f"{r['union_coverage_hit5']:.3f} |")
    md += ["", "**Reading:** a non-trivial 'KG✓&dense✗' and 'KG-only' share means the "
           "graph adds correct candidates the embedding/lexical retrievers miss — "
           "justifying its inclusion in the RRF fusion even when KG-alone Hit@5 is low. "
           "The union coverage upper-bounds what a perfect fuser could reach."]
    (ROOT / "kg-usefulness").mkdir(parents=True, exist_ok=True)
    (ROOT / "kg-usefulness" / "complementarity.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (ROOT / "kg-usefulness" / "complementarity.json").write_text(
        json.dumps({ds: r for ds, r in rows}, indent=2), encoding="utf-8")
    print("wrote complementarity.md/json")
    for ds, r in rows:
        if r:
            print(f"  {ds}: KG✓&dense✗={r['kg_correct_dense_wrong_pct']:.1f}% "
                  f"KG-only={r['kg_unique_vs_both_pct']:.1f}% union={r['union_coverage_hit5']:.3f}")


if __name__ == "__main__":
    main()

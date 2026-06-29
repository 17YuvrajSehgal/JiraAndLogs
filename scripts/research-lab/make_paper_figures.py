"""Generate publication-quality figures from paper-results/ for the ICSE paper.

Reads ONLY the committed result JSONs (no hardcoded numbers) and writes vector
PDF + PNG figures to ICSE/figures/. Every value is loaded from disk so the plots
can never drift from the reported results.

Usage:  python scripts/research-lab/make_paper_figures.py
"""
from __future__ import annotations
import json
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

PR = Path("paper-results")
OUT = Path("ICSE/figures"); OUT.mkdir(parents=True, exist_ok=True)
DS = ["online-boutique", "otel-demo", "wol-v3"]
NAME = {"online-boutique": "Online\nBoutique", "otel-demo": "OTel\nDemo", "wol-v3": "World of\nLogs"}

plt.rcParams.update({
    "font.family": "serif", "font.size": 9, "axes.titlesize": 9,
    "axes.labelsize": 9, "legend.fontsize": 7.5, "xtick.labelsize": 8,
    "ytick.labelsize": 8, "axes.spines.top": False, "axes.spines.right": False,
    "figure.dpi": 150, "savefig.bbox": "tight", "savefig.pad_inches": 0.02,
})
# colorblind-friendly palette (Okabe-Ito)
C = {"ours": "#0072B2", "hybrid": "#D55E00", "prior": "#999999", "llm": "#CC79A7",
     "graph": "#E69F00", "good": "#009E73", "bad": "#D55E00"}


def _load(p):
    try: return json.loads(Path(p).read_text())
    except Exception: return None

def _save(fig, name):
    fig.savefig(OUT / f"{name}.pdf"); fig.savefig(OUT / f"{name}.png", dpi=200)
    plt.close(fig); print(f"  wrote {name}.pdf/.png")


def fig_retrieval():
    """Grouped bars: Hit@5 per method across datasets."""
    def cas(ds, m): r = _load(PR/"retrieval-cascades"/ds/f"{m}-mode3-results.json"); return r["coarse"]["hit_at_5"] if r else None
    def bse(fam, ds, m): r = _load(PR/"baselines"/fam/ds/f"{m}-results.json"); return r["coarse"]["hit_at_5"] if r else None
    rows = [
        ("BM25 (lexical)",      C["prior"], lambda d: bse("tfidf", d, "tfidf")),
        ("BGE (dense, 0-shot)", C["prior"], lambda d: bse("sota-dense", d, "bge")),
        ("LLM-RAG",             C["llm"],   lambda d: bse("llm-rag", d, "llm-rag")),
        ("BiEncoder (ours)",    C["ours"],  lambda d: cas(d, "biencoder")),
        ("Hybrid (ours)",       C["hybrid"],lambda d: cas(d, "hybrid-rrf")),
    ]
    fig, ax = plt.subplots(figsize=(7.0, 2.5))
    x = np.arange(len(DS)); w = 0.16
    for i, (lab, col, fn) in enumerate(rows):
        vals = [fn(d) or 0 for d in DS]
        ax.bar(x + (i - 2) * w, vals, w, label=lab, color=col, edgecolor="black", linewidth=0.3)
    ax.set_xticks(x); ax.set_xticklabels([NAME[d].replace("\n", " ") for d in DS])
    ax.set_ylabel("Hit@5"); ax.set_ylim(0, 1.05)
    ax.legend(ncol=5, loc="upper center", bbox_to_anchor=(0.5, 1.18), frameon=False, columnspacing=1.0)
    ax.grid(axis="y", alpha=0.3, linewidth=0.4)
    _save(fig, "fig_retrieval_hit5")


def fig_triage():
    """The reframing: triage PR-AUC saturated on synthetic, at chance on real."""
    pr, acc = [], []
    for d in DS:
        rep = _load(PR/"triage-leaderboard"/d/"report.json")
        h = (rep or {}).get("headline", {}).get("hist_gradient_boosting_numeric", {})
        pr.append(h.get("triage.pr_auc", np.nan))
        ae = _load(PR/"agent-end-to-end"/d/"agent-eval.json")
        acc.append((ae or {}).get("triage_accuracy", np.nan))
    fig, ax = plt.subplots(figsize=(3.3, 2.5))
    x = np.arange(len(DS)); w = 0.38
    ax.bar(x - w/2, pr, w, label="Classifier PR-AUC", color=C["ours"], edgecolor="black", linewidth=0.3)
    ax.bar(x + w/2, acc, w, label="Agent triage acc.", color=C["graph"], edgecolor="black", linewidth=0.3)
    ax.axhline(0.5, ls="--", lw=0.9, color=C["bad"])
    ax.text(2.35, 0.52, "chance", color=C["bad"], fontsize=7, va="bottom", ha="right")
    ax.set_xticks(x); ax.set_xticklabels([NAME[d].replace("\n", " ") for d in DS], fontsize=7.5)
    ax.set_ylabel("score"); ax.set_ylim(0, 1.05)
    ax.legend(frameon=False, loc="lower left", fontsize=7)
    ax.grid(axis="y", alpha=0.3, linewidth=0.4)
    _save(fig, "fig_triage_reframing")


def fig_fusion_scale():
    """Trend: fusion benefit (Hybrid - BiEncoder Hit@5) vs memory size."""
    xs, ys, labs = [], [], []
    for d in DS:
        h = _load(PR/"retrieval-cascades"/d/"hybrid-rrf-mode3-results.json")
        b = _load(PR/"retrieval-cascades"/d/"biencoder-mode3-results.json")
        mem = _load(PR/"baselines"/"sota-dense"/d/"bge-results.json")  # has n_memory
        if not (h and b and mem): continue
        xs.append(mem["n_memory"])
        ys.append(h["coarse"]["hit_at_5"] - b["coarse"]["hit_at_5"])
        labs.append(NAME[d].replace("\n", " "))
    fig, ax = plt.subplots(figsize=(3.3, 2.5))
    ax.axhline(0, ls="-", lw=0.8, color="black")
    order = np.argsort(xs)
    xs = np.array(xs)[order]; ys = np.array(ys)[order]; labs = [labs[i] for i in order]
    ax.plot(xs, ys, "-o", color=C["hybrid"], ms=7, lw=1.4)
    for xi, yi, l in zip(xs, ys, labs):
        ax.annotate(l, (xi, yi), textcoords="offset points",
                    xytext=(0, 9 if yi >= 0 else -14), ha="center", fontsize=7.5)
    ax.set_xscale("log")
    ax.set_xlabel("memory corpus size (incidents)")
    ax.set_ylabel(r"$\Delta$ Hit@5  (Hybrid $-$ BiEncoder)")
    ax.grid(alpha=0.3, linewidth=0.4)
    ax.margins(y=0.25)
    _save(fig, "fig_fusion_vs_scale")


def fig_forest():
    """Forest plot of Hybrid-vs-X Hit@5 deltas with 95% CIs (BH-corrected)."""
    d = _load(PR/"robustness"/"significance-bh.json")
    if not d: print("  (skip forest: no significance-bh.json)"); return
    rows = [r for r in d["results"] if "KG-effect" not in r["comparison"]]
    rows = sorted(rows, key=lambda r: r["delta_hit5"])
    labels = [r["comparison"].replace("wol-v3", "WoL").replace("otel-demo", "OTel")
              .replace("online-boutique", "OB").replace(": Hybrid vs", ":") for r in rows]
    fig, ax = plt.subplots(figsize=(3.4, 4.0))
    y = np.arange(len(rows))
    for i, r in enumerate(rows):
        lo, hi = r["ci95"]; col = C["good"] if r["significant_bh"] else C["prior"]
        ax.plot([lo, hi], [i, i], color=col, lw=1.6)
        ax.plot(r["delta_hit5"], i, "o", color=col, ms=4.5)
    ax.axvline(0, ls="--", lw=0.8, color="black")
    ax.set_yticks(y); ax.set_yticklabels(labels, fontsize=6.6)
    ax.set_xlabel(r"$\Delta$ Hit@5 vs Hybrid (95% CI)")
    ax.plot([], [], color=C["good"], lw=1.6, label="significant (BH)")
    ax.plot([], [], color=C["prior"], lw=1.6, label="n.s.")
    ax.legend(frameon=False, loc="lower right", fontsize=6.8)
    ax.grid(axis="x", alpha=0.3, linewidth=0.4)
    _save(fig, "fig_significance_forest")


def fig_cost():
    """Cost saved by capability gating per dataset."""
    vals = []
    for d in DS:
        r = _load(PR/"agent-value"/d/"cost-vs-cascade.json")
        vals.append((r or {}).get("summary", {}).get("savings_pct", {}).get("wall", np.nan))
    fig, ax = plt.subplots(figsize=(3.3, 2.4))
    x = np.arange(len(DS))
    ax.bar(x, vals, 0.55, color=C["ours"], edgecolor="black", linewidth=0.3)
    for xi, v in zip(x, vals):
        ax.text(xi, v + 1.5, f"{v:.0f}%", ha="center", fontsize=8)
    ax.set_xticks(x); ax.set_xticklabels([NAME[d].replace("\n", " ") for d in DS], fontsize=7.5)
    ax.set_ylabel("per-window cost saved (%)"); ax.set_ylim(0, 100)
    ax.grid(axis="y", alpha=0.3, linewidth=0.4)
    _save(fig, "fig_cost_savings")


def fig_complementarity():
    """KG complementarity: unique correct hits per retriever + union coverage."""
    c = _load(PR/"kg-usefulness"/"complementarity.json")
    if not c: print("  (skip complementarity)"); return
    keymap = {"online-boutique": "online-boutique", "otel-demo": "otel-demo", "wol-v3": "wol-v3"}
    kg_only, kg_dense, union = [], [], []
    for d in DS:
        r = c.get(keymap[d]) or {}
        kg_dense.append(r.get("kg_correct_dense_wrong_pct", np.nan))
        kg_only.append(r.get("kg_unique_vs_both_pct", np.nan))
        union.append(r.get("union_coverage_hit5", np.nan) * 100)
    fig, ax = plt.subplots(figsize=(3.3, 2.4))
    x = np.arange(len(DS)); w = 0.36
    ax.bar(x - w/2, kg_dense, w, label="KG right, dense wrong", color=C["graph"], edgecolor="black", linewidth=0.3)
    ax.bar(x + w/2, kg_only, w, label="KG uniquely right", color=C["hybrid"], edgecolor="black", linewidth=0.3)
    ax.set_xticks(x); ax.set_xticklabels([NAME[d].replace("\n", " ") for d in DS], fontsize=7.5)
    ax.set_ylabel("% of windows-with-gold")
    ax.legend(frameon=False, fontsize=7, loc="upper right")
    ax.grid(axis="y", alpha=0.3, linewidth=0.4)
    _save(fig, "fig_kg_complementarity")


def fig_gold():
    """LLM-as-judge gold validation: gold vs random control scores."""
    g, rnd = [], []
    for d in DS:
        r = _load(PR/"gold-validation"/d/"llm-judge-gold-results.json")
        g.append((r or {}).get("gold_mean_score", np.nan))
        rnd.append((r or {}).get("random_mean_score", np.nan))
    fig, ax = plt.subplots(figsize=(3.3, 2.4))
    x = np.arange(len(DS)); w = 0.38
    ax.bar(x - w/2, g, w, label="gold match", color=C["good"], edgecolor="black", linewidth=0.3)
    ax.bar(x + w/2, rnd, w, label="random control", color=C["prior"], edgecolor="black", linewidth=0.3)
    ax.set_xticks(x); ax.set_xticklabels([NAME[d].replace("\n", " ") for d in DS], fontsize=7.5)
    ax.set_ylabel("LLM-judge relevance (1--5)"); ax.set_ylim(0, 5)
    ax.legend(frameon=False, fontsize=7)
    ax.grid(axis="y", alpha=0.3, linewidth=0.4)
    _save(fig, "fig_gold_validation")


def fig_seeds():
    """Multi-seed BiEncoder Hit@5 (mean +/- std) on synthetic datasets."""
    labels, means, stds = [], [], []
    for d in ("online-boutique", "otel-demo"):
        vals = []
        s42 = _load(PR/"retrieval-cascades"/d/"biencoder-mode3-results.json")
        if s42: vals.append(s42["coarse"]["hit_at_5"])
        for s in (1, 2):
            r = _load(PR/"robustness"/"multiseed"/d/f"seed{s}"/"biencoder-mode3-results.json")
            if r: vals.append(r["coarse"]["hit_at_5"])
        if vals:
            labels.append(NAME[d].replace("\n", " ")); means.append(np.mean(vals)); stds.append(np.std(vals))
    if not labels: print("  (skip seeds)"); return
    fig, ax = plt.subplots(figsize=(2.6, 2.4))
    x = np.arange(len(labels))
    ax.bar(x, means, 0.5, yerr=stds, capsize=4, color=C["ours"], edgecolor="black", linewidth=0.3)
    ax.set_xticks(x); ax.set_xticklabels(labels, fontsize=8)
    ax.set_ylabel("BiEncoder Hit@5 (3 seeds)"); ax.set_ylim(0, 1.0)
    ax.grid(axis="y", alpha=0.3, linewidth=0.4)
    _save(fig, "fig_robustness_seeds")


def main():
    print("Generating figures from paper-results/ ...")
    for fn in (fig_retrieval, fig_triage, fig_fusion_scale, fig_forest, fig_cost,
               fig_complementarity, fig_gold, fig_seeds):
        try: fn()
        except Exception as e: print(f"  FAILED {fn.__name__}: {e}")
    print(f"Done -> {OUT}/")


if __name__ == "__main__":
    main()

"""Generate publication-quality figures from paper-results/ for the ICSE paper.

Reads ONLY the committed result JSONs (no hardcoded numbers) and writes vector
PDF + PNG figures to ICSE/figures/. Every value is loaded from disk so the plots
can never drift from the reported results.

Figures fall into two groups:

  PAPER figures (referenced in ICSE/sections/*.tex):
    - fig_significance_forest : BH-corrected Hit@5 deltas, Hybrid vs each method
    - fig_triage_reframing    : classifier ROC-AUC, synthetic saturated vs real-at-chance
    - fig_adaptive_execution  : tool budget buys latency not accuracy; some tools hurt

  SUPPLEMENTARY figures (slides / appendix; not wired into the manuscript):
    - fig_retrieval_hit5, fig_cost_savings, fig_kg_complementarity,
      fig_gold_validation, fig_robustness_seeds

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
NAME1 = {k: v.replace("\n", " ") for k, v in NAME.items()}

plt.rcParams.update({
    "font.family": "serif", "font.size": 9, "axes.titlesize": 9,
    "axes.labelsize": 9, "legend.fontsize": 7.5, "xtick.labelsize": 8,
    "ytick.labelsize": 8, "axes.spines.top": False, "axes.spines.right": False,
    "figure.dpi": 150, "savefig.bbox": "tight", "savefig.pad_inches": 0.02,
})
# colorblind-friendly palette (Okabe-Ito)
C = {"ours": "#0072B2", "hybrid": "#D55E00", "prior": "#999999", "llm": "#CC79A7",
     "graph": "#E69F00", "good": "#009E73", "bad": "#D55E00", "ink": "#333333"}


def _load(p):
    try: return json.loads(Path(p).read_text())
    except Exception: return None

def _save(fig, name):
    fig.savefig(OUT / f"{name}.pdf"); fig.savefig(OUT / f"{name}.png", dpi=200)
    plt.close(fig); print(f"  wrote {name}.pdf/.png")


# ───────────────────────────── PAPER FIGURES ──────────────────────────────

def fig_significance_forest():
    """Forest plot of Hybrid-vs-X Hit@5 deltas, grouped by dataset, BH-corrected.

    The strongest, most rigorous result we have: every pairwise Hit@5 comparison
    with its paired-bootstrap 95% CI and Benjamini-Hochberg significance. Grouped
    by dataset so the reader sees the head/tail story at a glance; the off-scale
    KG delta on real data is clipped with an explicit value annotation rather than
    compressing the interesting +/-0.1 region.
    """
    d = _load(PR / "robustness" / "significance-bh.json")
    if not d:
        print("  (skip forest: no significance-bh.json)"); return
    # method label cleanup; exclude the +/-graph isolation (that is RQ on KG, not a method race)
    METH = {"BiEncoder": "vs BiEncoder (dense)", "BM25(fair)": "vs BM25 (lexical)",
            "BGE-dense": "vs BGE (zero-shot)", "LLM-RAG": "vs LLM-RAG",
            "KG": "vs Knowledge Graph"}
    def parse(r):
        ds, _, rest = r["comparison"].partition(": ")
        meth = rest.replace("Hybrid vs ", "")
        return ds, METH.get(meth, "vs " + meth)
    rows_by_ds = {ds: [] for ds in DS}
    for r in d["results"]:
        if "KG-effect" in r["comparison"]:
            continue
        ds, lab = parse(r)
        if ds in rows_by_ds:
            rows_by_ds[ds].append((lab, r))

    # assemble y positions bottom-up: WoL (bottom) -> OTel -> OB (top)
    xmin, xmax = -0.16, 0.40
    y = 0.0; yt, ytl, items, headers, seps = [], [], [], [], []
    for ds in reversed(DS):  # bottom-up
        rows = sorted(rows_by_ds[ds], key=lambda lr: lr[1]["delta_hit5"])
        for lab, r in rows:
            yt.append(y); ytl.append(lab); items.append((y, r)); y += 1.0
        headers.append((y - 0.5 + 0.15, NAME1[ds]))  # header sits above the group
        seps.append(y); y += 1.1  # gap before next group

    fig_h = 0.34 * len(items) + 0.9
    fig, ax = plt.subplots(figsize=(3.4, fig_h))
    for ypos, r in items:
        lo, hi = r["ci95"]; delta = r["delta_hit5"]
        col = C["good"] if r["significant_bh"] else C["prior"]
        off = hi > xmax  # off-scale (the real-data KG delta)
        hi_draw = min(hi, xmax - 0.005)
        ax.plot([max(lo, xmin), hi_draw], [ypos, ypos], color=col, lw=1.8, solid_capstyle="round")
        if off:
            ax.plot(xmax - 0.01, ypos, ">", color=col, ms=5)
            ax.text(xmax - 0.02, ypos + 0.18, f"$\\Delta$={delta:+.2f}", color=col,
                    fontsize=6.4, ha="right", va="bottom")
        else:
            ax.plot(delta, ypos, "o", color=col, ms=5, zorder=3)
    ax.axvline(0, ls="--", lw=0.9, color=C["ink"])
    for sy in seps[:-1]:
        ax.axhline(sy, color="0.85", lw=0.6)
    for hy, hname in headers:
        ax.text(xmin + 0.004, hy, hname, fontweight="bold", fontsize=8.2,
                ha="left", va="center")
    ax.set_yticks(yt); ax.set_yticklabels(ytl, fontsize=7.4)
    ax.set_ylim(-0.8, y - 0.8); ax.set_xlim(xmin, xmax)
    ax.set_xlabel(r"$\Delta$ \,Hit@5  vs Hybrid-RRF  (95\% CI)" if matplotlib.rcParams["text.usetex"]
                  else r"$\Delta$ Hit@5  vs Hybrid-RRF  (95% CI)")
    ax.plot([], [], "o-", color=C["good"], lw=1.8, label="significant (BH $q<0.05$)")
    ax.plot([], [], "o-", color=C["prior"], lw=1.8, label="not significant")
    ax.legend(frameon=False, loc="lower right", fontsize=6.8, handlelength=1.4)
    ax.grid(axis="x", alpha=0.25, linewidth=0.4)
    _save(fig, "fig_significance_forest")


def fig_triage_reframing():
    """The reframing (RQ4): classifier ROC-AUC is saturated on synthetic, exactly
    at chance (0.50) on real data.

    We plot ROC-AUC, for which 0.5 is the correct no-skill baseline (the previous
    version drew a 0.5 'chance' line under PR-AUC, whose no-skill baseline is the
    positive prevalence, not 0.5). PR-AUC values are annotated for completeness.
    """
    roc, pr = [], []
    for d in DS:
        rep = _load(PR / "triage-leaderboard" / d / "report.json")
        h = (rep or {}).get("headline", {}).get("hist_gradient_boosting_numeric", {})
        roc.append(h.get("triage.roc_auc", np.nan))
        pr.append(h.get("triage.pr_auc", np.nan))
    fig, ax = plt.subplots(figsize=(3.3, 2.5))
    x = np.arange(len(DS))
    colors = [C["ours"] if (v == v and v > 0.6) else C["bad"] for v in roc]
    bars = ax.bar(x, roc, 0.58, color=colors, edgecolor="black", linewidth=0.3)
    ax.axhline(0.5, ls="--", lw=1.0, color=C["ink"])
    ax.text(len(DS) - 1.5, 0.555, "chance (0.50)", color=C["ink"], fontsize=7,
            va="bottom", ha="center")
    for xi, (b, rv, pv) in enumerate(zip(bars, roc, pr)):
        if rv == rv:
            ax.text(xi, rv + 0.015, f"{rv:.2f}", ha="center", fontsize=7.5, fontweight="bold")
        if pv == pv:
            ax.text(xi, 0.045, f"PR-AUC\n{pv:.2f}", ha="center", fontsize=6.3, color="0.25")
    ax.set_xticks(x); ax.set_xticklabels([NAME1[d] for d in DS], fontsize=7.8)
    ax.set_ylabel("triage classifier ROC-AUC"); ax.set_ylim(0, 1.08)
    ax.grid(axis="y", alpha=0.3, linewidth=0.4)
    _save(fig, "fig_triage_reframing")


def fig_adaptive_execution():
    """RQ3 made visual, on the fully-instrumented Online Boutique system where the
    evidence-gathering tools actually fire: (a) spending more tool budget leaves
    retrieval accuracy flat while wall-time climbs several-fold; (b) no single tool
    is load-bearing and one (the trace reader) actively hurts top-1 retrieval.
    """
    fig, (axL, axR) = plt.subplots(1, 2, figsize=(7.0, 2.6))
    fig.subplots_adjust(wspace=0.55)

    # ── panel (a): OB budget curve — accuracy flat, wall-time rising ──
    bc = _load(PR / "agent-value" / "online-boutique" / "budget-curve.json")
    if not bc or not bc.get("rows"):
        print("  (skip adaptive_execution: no OB budget-curve)"); plt.close(fig); return
    rows = sorted(bc["rows"], key=lambda r: r["max_tool_calls"])
    xs = [r["max_tool_calls"] for r in rows]
    h5 = [r["hit_at_5"] for r in rows]
    h1 = [r["hit_at_1"] for r in rows]
    wall = [r.get("wall_seconds", np.nan) for r in rows]
    axL2 = axL.twinx(); axL2.spines["top"].set_visible(False)
    lh5, = axL.plot(xs, h5, "-o", color=C["ours"], ms=4, lw=1.7, label="Hit@5")
    lh1, = axL.plot(xs, h1, "-s", color=C["graph"], ms=3.5, lw=1.3, label="Hit@1")
    lw, = axL2.plot(xs, wall, "--^", color=C["ink"], ms=3.5, lw=1.3, label="wall-time")
    if wall[0] and wall[-1] == wall[-1] and wall[0] == wall[0]:
        axL2.annotate(f"$\\times${wall[-1]/wall[0]:.1f} cost", (xs[-1], wall[-1]),
                      textcoords="offset points", xytext=(-4, 3), ha="right",
                      fontsize=7, color=C["ink"])
    axL.set_ylim(0, 1.05); axL.set_xlabel("max evidence-tool calls per window")
    axL.set_ylabel("retrieval accuracy"); axL2.set_ylabel("wall-time (s)")
    axL.set_xticks(xs)
    axL.set_title("(a) more budget: flat accuracy, rising cost", fontsize=8.2)
    axL.legend(handles=[lh5, lh1, lw], frameon=True, loc="lower right", fontsize=7,
               handlelength=1.6, borderaxespad=0.6, framealpha=0.9, edgecolor="none")
    axL.grid(alpha=0.25, linewidth=0.4)

    # ── panel (b): single-tool effect on Hit@1 (synthetic, telemetry tools) ──
    TOOL = {"events": "events", "trace": "trace",
            "metrics": "metrics", "peers": "peers"}
    ta = _load(PR / "agent-value" / "online-boutique" / "tool-ablation.json")
    drew = False
    if ta and ta.get("all_subsets"):
        base = next((s for s in ta["all_subsets"] if s["subset_label"] == "none"), None)
        singles = {s["subset_label"]: s for s in ta["all_subsets"] if s.get("n_tools") == 1}
        if base and singles:
            b1 = base["hit_at_1"]
            labs, deltas = [], []
            for key in ("events", "trace", "metrics", "peers"):
                if key in singles:
                    labs.append(TOOL[key]); deltas.append(singles[key]["hit_at_1"] - b1)
            ypos = np.arange(len(labs))
            cols = [C["good"] if dv > 0 else (C["bad"] if dv < 0 else C["prior"]) for dv in deltas]
            axR.barh(ypos, deltas, 0.6, color=cols, edgecolor="black", linewidth=0.3)
            axR.axvline(0, color=C["ink"], lw=0.9)
            for yi, dv in zip(ypos, deltas):
                axR.text(dv + (0.0008 if dv >= 0 else -0.0008), yi, f"{dv:+.3f}",
                         va="center", ha="left" if dv >= 0 else "right", fontsize=6.8)
            axR.set_yticks(ypos); axR.set_yticklabels(labs, fontsize=7.6)
            axR.set_xlabel(r"$\Delta$ Hit@1 vs no tools")
            axR.set_title("(b) single-tool effect (Online Boutique)", fontsize=8.2)
            mx = max(abs(min(deltas)), abs(max(deltas))) * 1.5 or 0.01
            axR.set_xlim(-mx, mx)
            axR.grid(axis="x", alpha=0.25, linewidth=0.4)
            drew = True
    if not drew:
        axR.text(0.5, 0.5, "tool-ablation data unavailable", ha="center", va="center",
                 transform=axR.transAxes, fontsize=8, color="0.5")
        axR.set_axis_off()
    _save(fig, "fig_adaptive_execution")


# ──────────────────────────── SUPPLEMENTARY ───────────────────────────────

def fig_retrieval():
    """Grouped bars: Hit@5 per method across datasets (duplicates Table I; kept for slides)."""
    def cas(ds, m): r = _load(PR/"retrieval-cascades"/ds/f"{m}-mode3-results.json"); return r["coarse"]["hit_at_5"] if r else None
    def bse(fam, ds, m): r = _load(PR/"baselines"/fam/ds/f"{m}-results.json"); return r["coarse"]["hit_at_5"] if r else None
    rows = [
        ("TF-IDF (lexical)",    C["prior"], lambda d: bse("tfidf", d, "tfidf")),
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
    ax.set_xticks(x); ax.set_xticklabels([NAME1[d] for d in DS])
    ax.set_ylabel("Hit@5"); ax.set_ylim(0, 1.05)
    ax.legend(ncol=5, loc="upper center", bbox_to_anchor=(0.5, 1.18), frameon=False, columnspacing=1.0)
    ax.grid(axis="y", alpha=0.3, linewidth=0.4)
    _save(fig, "fig_retrieval_hit5")


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
        if v == v: ax.text(xi, v + 1.5, f"{v:.0f}%", ha="center", fontsize=8)
    ax.set_xticks(x); ax.set_xticklabels([NAME1[d] for d in DS], fontsize=7.5)
    ax.set_ylabel("per-window cost saved (%)"); ax.set_ylim(0, 100)
    ax.grid(axis="y", alpha=0.3, linewidth=0.4)
    _save(fig, "fig_cost_savings")


def fig_complementarity():
    """KG complementarity: unique correct hits per retriever."""
    c = _load(PR/"kg-usefulness"/"complementarity.json")
    if not c: print("  (skip complementarity)"); return
    kg_only, kg_dense = [], []
    for d in DS:
        r = c.get(d) or {}
        kg_dense.append(r.get("kg_correct_dense_wrong_pct", np.nan))
        kg_only.append(r.get("kg_unique_vs_both_pct", np.nan))
    fig, ax = plt.subplots(figsize=(3.3, 2.4))
    x = np.arange(len(DS)); w = 0.36
    ax.bar(x - w/2, kg_dense, w, label="KG right, dense wrong", color=C["graph"], edgecolor="black", linewidth=0.3)
    ax.bar(x + w/2, kg_only, w, label="KG uniquely right", color=C["hybrid"], edgecolor="black", linewidth=0.3)
    ax.set_xticks(x); ax.set_xticklabels([NAME1[d] for d in DS], fontsize=7.5)
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
    ax.set_xticks(x); ax.set_xticklabels([NAME1[d] for d in DS], fontsize=7.5)
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
            labels.append(NAME1[d]); means.append(np.mean(vals)); stds.append(np.std(vals))
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
    paper = (fig_significance_forest, fig_triage_reframing, fig_adaptive_execution)
    supp = (fig_retrieval, fig_cost, fig_complementarity, fig_gold, fig_seeds)
    print(" paper figures:")
    for fn in paper:
        try: fn()
        except Exception as e: print(f"  FAILED {fn.__name__}: {e}")
    print(" supplementary figures:")
    for fn in supp:
        try: fn()
        except Exception as e: print(f"  FAILED {fn.__name__}: {e}")
    print(f"Done -> {OUT}/")


if __name__ == "__main__":
    main()

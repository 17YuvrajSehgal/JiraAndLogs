"""Generate two new figures for the technical paper.

(1) g_series_novelty.pdf — novel-recall progression across the G-series
    that contribute to the L3 channel.
(2) pipeline_comparison.pdf — Hit@1 / Hit@5 / MRR / novel-recall bars
    for the cascade vs every single pipeline.

Run from this directory:
    python generate_extra_figures.py
"""
from __future__ import annotations
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path

OUT = Path(__file__).parent

plt.rcParams.update({
    "font.family": "serif",
    "font.size": 10,
    "axes.titlesize": 11,
    "axes.labelsize": 10,
    "legend.fontsize": 9,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
})


# --------------------------------------------------------------------------
# Figure 1: G-series novelty progression (cumulative effect of the KEEP phases)
# --------------------------------------------------------------------------
def fig_g_series_novelty():
    stages = ["v2f\nbaseline", "+G1\n(BiEncoder\nmixed-negs)",
              "+G4\n(agent\nfull coverage)", "+G7\n(learned\nL3 threshold)"]
    novel_recall = [0.1625, 0.1610, 0.3560, 0.7932]
    novel_precision = [0.9402, 0.9397, 0.9305, 0.9405]

    fig, ax1 = plt.subplots(figsize=(7.5, 3.4))
    x = np.arange(len(stages))
    width = 0.35

    bars_recall = ax1.bar(x - width/2, novel_recall, width,
                          color="#3470b8", label="Novel recall", alpha=0.9)
    bars_prec   = ax1.bar(x + width/2, novel_precision, width,
                          color="#d97726", label="Novel precision", alpha=0.9)

    for b, v in zip(bars_recall, novel_recall):
        ax1.text(b.get_x() + b.get_width()/2, v + 0.015,
                 f"{v:.3f}", ha="center", va="bottom", fontsize=8.5)
    for b, v in zip(bars_prec, novel_precision):
        ax1.text(b.get_x() + b.get_width()/2, v + 0.015,
                 f"{v:.3f}", ha="center", va="bottom", fontsize=8.5)

    ax1.set_xticks(x)
    ax1.set_xticklabels(stages)
    ax1.set_ylabel("Score")
    ax1.set_ylim(0, 1.08)
    ax1.set_title("L3 novelty: progression across the G-series KEEP phases")
    ax1.legend(loc="upper left", framealpha=0.95)
    ax1.grid(axis="y", alpha=0.25)

    # annotate the headline lift
    ax1.annotate(
        "+388% rel\n(at preserved precision)",
        xy=(3 - width/2, novel_recall[3]),
        xytext=(2.05, 0.55),
        arrowprops=dict(arrowstyle="->", color="black", lw=0.7),
        fontsize=9, ha="center", color="#222",
    )

    fig.tight_layout()
    fig.savefig(OUT / "g_series_novelty.pdf", bbox_inches="tight")
    fig.savefig(OUT / "g_series_novelty.png", dpi=180, bbox_inches="tight")
    plt.close(fig)
    print("wrote g_series_novelty.{pdf,png}")


# --------------------------------------------------------------------------
# Figure 2: Pipeline comparison (TCH vs each baseline)
# --------------------------------------------------------------------------
def fig_pipeline_comparison():
    pipelines = ["HGB", "BiEncoder", "Hybrid-RRF\nrule", "Hybrid-RRF\nLLM",
                 "logseq2vec", "KG-retrieval", "Agent", "TCH-Final"]
    hit1 = [0.0, 0.695, 0.583, 0.432, 0.483, 0.079, 0.386, 0.722]
    hit5 = [0.0, 0.789, 0.798, 0.667, 0.531, 0.556, 0.436, 0.912]
    mrr  = [0.0, 0.729, 0.669, 0.517, 0.498, 0.228, 0.405, 0.794]

    fig, ax = plt.subplots(figsize=(8.5, 3.4))
    x = np.arange(len(pipelines))
    width = 0.27

    b1 = ax.bar(x - width, hit1, width, color="#3470b8", label="Hit@1")
    b2 = ax.bar(x,         hit5, width, color="#5fa667", label="Hit@5")
    b3 = ax.bar(x + width, mrr,  width, color="#c04848", label="MRR")

    # outline the TCH bars
    for b in [b1[-1], b2[-1], b3[-1]]:
        b.set_edgecolor("black")
        b.set_linewidth(1.6)

    for b, v in zip(b2, hit5):
        if v > 0:
            ax.text(b.get_x() + b.get_width()/2, v + 0.015,
                    f"{v:.2f}", ha="center", va="bottom", fontsize=7.5)

    ax.set_xticks(x)
    ax.set_xticklabels(pipelines, fontsize=8.5)
    ax.set_ylabel("Score")
    ax.set_ylim(0, 1.05)
    ax.set_title("Per-pipeline retrieval vs TCH-Final on the 1,008-window v2 in-distribution test split")
    ax.legend(loc="upper left", framealpha=0.95)
    ax.grid(axis="y", alpha=0.25)
    ax.axvline(x=6.5, color="black", linestyle="--", alpha=0.4)

    fig.tight_layout()
    fig.savefig(OUT / "pipeline_comparison.pdf", bbox_inches="tight")
    fig.savefig(OUT / "pipeline_comparison.png", dpi=180, bbox_inches="tight")
    plt.close(fig)
    print("wrote pipeline_comparison.{pdf,png}")


# --------------------------------------------------------------------------
# Figure 3: Distractor robustness (recreated from G6 numbers, simpler version)
# --------------------------------------------------------------------------
def fig_distractor_robustness():
    ratios = [0, 10, 25, 50]
    hit1 = [0.7221, 0.7190, 0.6586, 0.6193]
    hit5 = [0.9124, 0.9094, 0.9003, 0.8943]
    mrr  = [0.7937, 0.7899, 0.7506, 0.7290]

    fig, ax = plt.subplots(figsize=(6.5, 3.2))
    ax.plot(ratios, hit5, "o-", color="#5fa667", label="Hit@5", lw=2, ms=7)
    ax.plot(ratios, hit1, "s-", color="#3470b8", label="Hit@1", lw=2, ms=7)
    ax.plot(ratios, mrr,  "^-", color="#c04848", label="MRR",   lw=2, ms=7)

    for r, v in zip(ratios, hit5):
        ax.annotate(f"{v:.3f}", (r, v), textcoords="offset points",
                    xytext=(0, 8), ha="center", fontsize=8)
    for r, v in zip(ratios, hit1):
        ax.annotate(f"{v:.3f}", (r, v), textcoords="offset points",
                    xytext=(0, -14), ha="center", fontsize=8)

    ax.set_xlabel("Distractor ratio (%)")
    ax.set_ylabel("Score")
    ax.set_xticks(ratios)
    ax.set_ylim(0.55, 1.0)
    ax.set_title("G6: Cascade robustness to memory noise (simulated)")
    ax.legend(loc="lower left", framealpha=0.95)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(OUT / "g6_distractor_robustness.pdf", bbox_inches="tight")
    fig.savefig(OUT / "g6_distractor_robustness.png", dpi=180, bbox_inches="tight")
    plt.close(fig)
    print("wrote g6_distractor_robustness.{pdf,png}")


# --------------------------------------------------------------------------
# Figure 4: G8 OOD vs in-distribution F1 by threshold
# --------------------------------------------------------------------------
def fig_g8_ood():
    thresholds = [0.30, 0.40, 0.50, 0.60, 0.70]
    id_f1  = [0.890, 0.875, 0.861, 0.866, 0.865]
    ood_f1 = [0.788, 0.779, 0.732, 0.747, 0.748]

    fig, ax = plt.subplots(figsize=(6.5, 3.2))
    ax.plot(thresholds, id_f1, "o-", color="#3470b8",
            label="In-distribution (5-fold CV)", lw=2, ms=7)
    ax.plot(thresholds, ood_f1, "s--", color="#d97726",
            label="OOD (leave-one-family-out)", lw=2, ms=7)
    ax.fill_between(thresholds, ood_f1, id_f1, alpha=0.15, color="gray")

    for t, v in zip(thresholds, id_f1):
        ax.annotate(f"{v:.3f}", (t, v), textcoords="offset points",
                    xytext=(0, 7), ha="center", fontsize=7.5)
    for t, v in zip(thresholds, ood_f1):
        ax.annotate(f"{v:.3f}", (t, v), textcoords="offset points",
                    xytext=(0, -13), ha="center", fontsize=7.5)

    ax.set_xlabel("Decision threshold")
    ax.set_ylabel("Novelty F1")
    ax.set_xticks(thresholds)
    ax.set_ylim(0.65, 0.95)
    ax.set_title("G8: OOD generalization of the G7 learned classifier")
    ax.legend(loc="lower right", framealpha=0.95)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(OUT / "g8_ood_f1.pdf", bbox_inches="tight")
    fig.savefig(OUT / "g8_ood_f1.png", dpi=180, bbox_inches="tight")
    plt.close(fig)
    print("wrote g8_ood_f1.{pdf,png}")


# --------------------------------------------------------------------------
# Figure 5: L1 stacker coefficients
# --------------------------------------------------------------------------
def fig_l1_coefs():
    features = ["HGB\ntriage", "KG-ret\ntriage", "BiEnc\ntriage",
                "logseq2vec\ntriage", "HRRF-LLM\ntriage", "HRRF-rule\ntriage",
                "bias"]
    coefs    = [8.221, 0.525, 0.292, 0.116, 0.112, -0.048, -4.755]
    colors = ["#3470b8" if c > 0 else "#c04848" for c in coefs]

    fig, ax = plt.subplots(figsize=(7.5, 3.0))
    bars = ax.bar(features, coefs, color=colors, alpha=0.9)
    for b, v in zip(bars, coefs):
        ax.text(b.get_x() + b.get_width()/2,
                v + (0.25 if v >= 0 else -0.5),
                f"{v:+.3f}", ha="center", va="center", fontsize=9)
    ax.axhline(0, color="black", lw=0.5)
    ax.set_ylabel("Coefficient")
    ax.set_title("L1 stacker coefficients (LogReg, class-balanced, 5-fold CV)")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(OUT / "l1_stacker_coefs.pdf", bbox_inches="tight")
    fig.savefig(OUT / "l1_stacker_coefs.png", dpi=180, bbox_inches="tight")
    plt.close(fig)
    print("wrote l1_stacker_coefs.{pdf,png}")


if __name__ == "__main__":
    fig_g_series_novelty()
    fig_pipeline_comparison()
    fig_distractor_robustness()
    fig_g8_ood()
    fig_l1_coefs()
    print("done")

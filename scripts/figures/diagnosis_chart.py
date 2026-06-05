"""Phase E figure: time-to-diagnose bar chart.

Reads `diagnosis_sim_phase-b.json` and produces a bar chart of mean
minutes-per-incident across pipelines.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sim", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()

    data = json.loads(args.sim.read_text(encoding="utf-8"))
    per = data["per_pipeline"]
    names = list(per)
    means = [per[n]["mean_minutes"] for n in names]
    find_rates = [per[n]["find_rate"] for n in names]

    pretty = {
        "hist_gradient_boosting_numeric": "HGB\n(telemetry only)",
        "memorygraph_v2_sota_nw080": "SOTA\n(off-the-shelf reranker)",
        "memorygraph_v2_sota_nw080_ft": "SOTA + FT reranker\n(this paper)",
    }
    labels = [pretty.get(n, n) for n in names]

    fig, ax = plt.subplots(figsize=(8, 5), dpi=120)
    bars = ax.bar(labels, means,
                  color=["#888888", "#1f77b4", "#d62728"])
    ax.set_ylabel("Mean time-to-diagnose (minutes)")
    ax.set_title(
        "Simulated time-to-diagnose per incident "
        "(317 resolvable test windows)\n"
        f"engineer scans top-{data['params']['top_k']} candidates @ "
        f"{data['params']['t_per_candidate_s']:.0f}s each, "
        f"{data['params']['t_fallback_s']/60:.0f}-min fallback when none helpful"
    )
    # Annotate with mean + find rate
    for i, (b, m, fr) in enumerate(zip(bars, means, find_rates)):
        ax.text(
            b.get_x() + b.get_width() / 2,
            m + 0.3,
            f"{m:.2f}min\nfind-rate {fr*100:.1f}%",
            ha="center", va="bottom", fontsize=10, fontweight="bold",
        )
    ax.set_ylim(0, max(means) * 1.18)
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out, bbox_inches="tight")
    fig.savefig(args.out.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)
    print(f"[diagnosis_chart] wrote {args.out} (+pdf)")


if __name__ == "__main__":
    main()

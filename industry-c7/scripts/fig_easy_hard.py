"""Figure: Acc@1 and Acc@5 split into the reports that name a faulty file (easy)
and the reports that name none (hard). Top group: every system at the file
level on the 1,000-instance sample. Bottom group: the two agents at the
function level on the 26,537 paired evaluation instances.

    python scripts/fig_easy_hard.py            -> paper/figures/easy-hard.pdf + .png

Reads data/results/agentic-baselines.json (ours, LocAgent-style, CoSIL-style),
paper/tables/sources.json (model alone, re-ranker, and the paired Wp/Lp strata
for the function level) and data/results/paper-numbers.json (retrieval layer on
the sample). The easy value of the sample systems is derived from the all/hard
pair: easy = (all*n - hard*n_hard) / (n - n_hard).
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
AB = json.loads((ROOT / "data/results/agentic-baselines.json").read_text(encoding="utf-8"))
SRC = json.loads((ROOT / "paper/tables/sources.json").read_text(encoding="utf-8"))
PN = json.loads((ROOT / "data/results/paper-numbers.json").read_text(encoding="utf-8"))
n, n_hard = AB["n_common"], AB["n_hard"]
n_easy = n - n_hard


def split(all_, hard):
    """(easy, hard) in percent from the all/hard pair."""
    return 100 * (all_ * n - hard * n_hard) / n_easy, 100 * hard


def sys_row(name, d, a1="acc@1", h1="hard_acc@1", a5="acc@5", h5="hard_acc@5"):
    e1, hh1 = split(d[a1], d[h1]); e5, hh5 = split(d[a5], d[h5])
    return name, {1: (e1, hh1), 5: (e5, hh5)}


rs = PN["retrieval_sample"]
X = SRC["agents"]["extra"]
sample = [
    sys_row("retrieval layer", {"acc@1": rs["all"]["acc@1"], "hard_acc@1": rs["hard"]["acc@1"], "acc@5": rs["all"]["acc@5"], "hard_acc@5": rs["hard"]["acc@5"]}),
    sys_row("CoSIL-style", AB["systems"]["cosil"]),
    sys_row("model alone", X["llm_alone"]),
    sys_row("LocAgent-style", AB["systems"]["locagent"]),
    sys_row("model as re-ranker", X["llm_rerank"]),
    sys_row("Inquest", AB["systems"]["ours"]),
]
sample.sort(key=lambda r: r[1][1][1])              # by hard Acc@1
H = SRC["headline"]
funcs = [(name, {k: (100 * H[key]["easy"][f"region_acc@{k}"], 100 * H[key]["hard"][f"region_acc@{k}"]) for k in (1, 5)})
         for name, key in (("unconstrained loop", "Lp"), ("Inquest", "Wp"))]
funcs.sort(key=lambda r: r[1][1][1])
for name, d in sample + funcs:
    print(f"{name:28} " + "  ".join(f"@{k} easy {e:5.1f} hard {h:5.1f}" for k, (e, h) in d.items()))

plt.rcParams.update({"font.family": "serif", "font.size": 8, "axes.linewidth": 0.5})
fig, axes = plt.subplots(1, 2, figsize=(3.5, 2.85), sharey=True, gridspec_kw={"wspace": 0.14})
GREEN, GREY, DARK, LIGHT = "#2a7f4f", "#b0b0b0", "#333333", "#8a8a8a"
GAP = 1.1
ys_f = list(range(len(funcs)))
ys_s = [len(funcs) + GAP + i for i in range(len(sample))]
rows = list(zip(ys_f, funcs)) + list(zip(ys_s, sample))
top = ys_s[-1]
for ax, k in zip(axes, (1, 5)):
    for y, (name, d) in rows:
        e, h = d[k]
        ours = name == "Inquest"
        c = GREEN if ours else DARK
        ax.plot([h, e], [y, y], color=GREEN if ours else GREY, lw=1.4 if ours else 0.9, solid_capstyle="round", zorder=1)
        ax.plot(e, y, "o", ms=4.2, mfc="white", mec=c, mew=1.1, zorder=3)
        ax.plot(h, y, "o", ms=4.2, mfc=c, mec=c, zorder=3)
        ax.text(h - 4, y, f"{h:.0f}", ha="right", va="center", fontsize=6.2, color=c)
        ax.text(e + 4, y, f"{e:.0f}", ha="left", va="center", fontsize=6.2, color=c)
    ax.set_xlim(0, 100); ax.set_ylim(-0.75, top + 1.75); ax.set_facecolor("none")
    ax.set_xticks(range(0, 101, 25)); ax.tick_params(axis="x", length=2.5, labelsize=6.3, colors=DARK)
    ax.set_xlabel(f"Acc@{k} (%)", fontsize=7, labelpad=2)
    for s in ("top", "right", "left"): ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(LIGHT)
    ax.tick_params(axis="y", length=0, pad=3)
axes[0].set_yticks([y for y, _ in rows])
axes[0].set_yticklabels([r[0] for _, r in rows], fontsize=7)
for lbl in axes[0].get_yticklabels():
    if lbl.get_text() == "Inquest":
        lbl.set_color(GREEN); lbl.set_fontweight("bold")
axes[0].text(0, top + 0.95, "FILE LEVEL · 1,000-INSTANCE SAMPLE", ha="left", va="center", fontsize=5.6, color=LIGHT, clip_on=False)
axes[0].text(0, len(funcs) - 1 + 0.95, "FUNCTION LEVEL · 26,537 PAIRED INSTANCES", ha="left", va="center", fontsize=5.6, color=LIGHT, clip_on=False)
hard_h, = axes[0].plot([], [], "o", ms=4.2, mfc=DARK, mec=DARK)
easy_h, = axes[0].plot([], [], "o", ms=4.2, mfc="white", mec=DARK, mew=1.1)
fig.legend([hard_h, easy_h], ["hard: report names no faulty file", "easy: names one"],
           loc="upper center", ncol=2, bbox_to_anchor=(0.56, 1.0), frameon=False, fontsize=6.3, handletextpad=0.35, columnspacing=1.6)
fig.subplots_adjust(left=0.30, right=0.955, top=0.905, bottom=0.145, wspace=0.16)
out = ROOT / "paper/figures/easy-hard"
fig.savefig(out.with_suffix(".pdf")); fig.savefig(out.with_suffix(".png"), dpi=220)
print("->", out.with_suffix(".pdf"))

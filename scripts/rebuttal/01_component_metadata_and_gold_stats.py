"""Rebuttal analysis: component-metadata quality, gold-relation stats, KG/gold vocabulary overlap."""
import json, collections, statistics, sys

G = "C:/workplace/JiraAndLogs/data/derived/global/2026-06-17-wol-real-v3-global"

# ---------- 1. component metadata quality on WoL queries ----------
split_counts = collections.Counter()
comp_present = collections.Counter()      # (split, has_comp)
ncomp = collections.Counter()
per_proj_comps = collections.defaultdict(set)
tw_test_ids = set()
label_by_split = collections.Counter()
test_rows_no_comp_tw = 0
test_rows_tw = 0

with open(f"{G}/global-triage-examples.jsonl", encoding="utf-8") as f:
    for line in f:
        d = json.loads(line)
        sp = d.get("split"); lab = d.get("triage_label"); proj = d.get("wol_project")
        comps = d.get("triage_components") or []
        split_counts[sp] += 1
        label_by_split[(sp, lab)] += 1
        comp_present[(sp, bool(comps))] += 1
        ncomp[len(comps)] += 1
        for c in comps:
            per_proj_comps[proj].add(c)
        if sp == "test" and lab == "ticket_worthy":
            test_rows_tw += 1
            tw_test_ids.add(d["window_id"])
            if not comps:
                test_rows_no_comp_tw += 1

print("=== 1. WoL query rows ===")
print("rows per split:", dict(split_counts))
print("labels per split:", {f"{k[0]}/{k[1]}": v for k, v in sorted(label_by_split.items(), key=lambda x: str(x[0]))})
tot = sum(split_counts.values())
has = sum(v for (sp, h), v in comp_present.items() if h)
print(f"ALL rows with >=1 component: {has}/{tot} = {has/tot:.4f}")
for sp in ["train", "validation", "test"]:
    h = comp_present[(sp, True)]; n = split_counts[sp]
    print(f"  {sp}: {h}/{n} = {h/n:.4f} have >=1 component")
print(f"test ticket_worthy rows: {test_rows_tw}, of which ZERO components: {test_rows_no_comp_tw} = {test_rows_no_comp_tw/max(1,test_rows_tw):.4f}")
print("component-count distribution (all rows):", dict(sorted(ncomp.items())[:8]))
print("distinct component vocab per project (top/bottom):")
sizes = sorted(((len(v), k) for k, v in per_proj_comps.items()), reverse=True)
for s, k in sizes[:5] + sizes[-3:]:
    print(f"   {k}: {s} distinct components")

# ---------- 2. gold relation statistics ----------
def gold_stats(path, label):
    n_rows = 0; n_nonempty = 0; sizes = []
    per_q = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            wid = d.get("window_id")
            ids = d.get("matched_memory_issue_ids") or []
            if wid in tw_test_ids:
                n_rows += 1
                per_q[wid] = ids
                if ids:
                    n_nonempty += 1
                    sizes.append(len(ids))
    print(f"\n=== 2. gold relation: {label} (test ticket_worthy only) ===")
    print(f"  rows={n_rows}  with>=1 match={n_nonempty} ({n_nonempty/max(1,n_rows):.4f})  zero-match={n_rows-n_nonempty}")
    if sizes:
        sizes.sort()
        print(f"  matches/query: mean={statistics.mean(sizes):.1f} median={sizes[len(sizes)//2]} "
              f"p10={sizes[len(sizes)//10]} p90={sizes[int(len(sizes)*0.9)]} max={max(sizes)}")
    return per_q

# peek key names first
with open(f"{G}/window-memory-matchings.jsonl", encoding="utf-8") as f:
    print("\nmatchings row keys:", list(json.loads(f.readline()).keys()))

coarse = gold_stats(f"{G}/window-memory-matchings.jsonl", "COARSE (project + >=1 component)")
strong = gold_stats(f"{G}/window-memory-matchings-strong.jsonl", "STRICT (coarse + symptom Jaccard>0.15)")

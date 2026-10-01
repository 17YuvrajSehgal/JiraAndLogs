"""Random-ranker baselines + KG/gold vocabulary overlap (leakage check)."""
import json, collections, statistics, random

G = "C:/workplace/JiraAndLogs/data/derived/global/2026-06-17-wol-real-v3-global"
N_MEM = 38642

# ---- A. random-ranker expectation under each relation ----
def rand_expect(path, label):
    sizes = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            ids = d.get("matched_memory_issue_ids") or []
            if d.get("triage_label") == "ticket_worthy" and ids:
                sizes.append(len(ids))
    # E[Hit@k] for a uniformly random ranker drawing k distinct items w/o replacement
    def hit_at_k(R, k, N=N_MEM):
        p_miss = 1.0
        for i in range(k):
            p_miss *= (N - R - i) / (N - i)
        return 1 - p_miss
    h1 = statistics.mean(hit_at_k(R, 1) for R in sizes)
    h5 = statistics.mean(hit_at_k(R, 5) for R in sizes)
    print(f"{label}: n={len(sizes)} mean|gold|={statistics.mean(sizes):.1f} "
          f"({statistics.mean(sizes)/N_MEM*100:.2f}% of memory) -> "
          f"random Hit@1={h1:.4f} Hit@5={h5:.4f}")
    return h1, h5

print("=== A. Random-ranker expectation (WoL, memory N=38,642) ===")
rand_expect(f"{G}/window-memory-matchings.jsonl", "COARSE")
rand_expect(f"{G}/window-memory-matchings-strong.jsonl", "STRICT")

# ---- B. KG-extracted components vs Jira metadata components ----
print("\n=== B. Leakage check: LLM-extracted KG entities vs Jira `components` metadata ===")
kg_comps, kg_svcs, kg_syms, kg_err = set(), set(), set(), set()
n_kg = 0
with open(f"{G}/v2_kg_extractions/all_extractions.jsonl", encoding="utf-8") as f:
    for line in f:
        d = json.loads(line); n_kg += 1
        kg_comps.update(c.strip().lower() for c in (d.get("components") or []))
        kg_svcs.update(c.strip().lower() for c in (d.get("affected_services") or []))
        kg_syms.update(c.strip().lower() for c in (d.get("symptoms") or []))
        kg_err.update(c.strip().lower() for c in (d.get("error_classes") or []))
print(f"KG memory extractions: {n_kg}")
print(f"  distinct extracted components={len(kg_comps)} services={len(kg_svcs)} "
      f"error_classes={len(kg_err)} symptoms={len(kg_syms)}")

jira_comps = set()
per_row_overlap = []
with open(f"{G}/global-triage-examples.jsonl", encoding="utf-8") as f:
    for line in f:
        d = json.loads(line)
        cs = {c.strip().lower() for c in (d.get("triage_components") or [])}
        jira_comps |= cs
print(f"  distinct Jira metadata components (gold vocabulary)={len(jira_comps)}")
inter = kg_comps & jira_comps
print(f"  vocabulary intersection = {len(inter)} terms "
      f"({len(inter)/max(1,len(jira_comps))*100:.1f}% of the gold vocabulary, "
      f"{len(inter)/max(1,len(kg_comps))*100:.1f}% of the extracted vocabulary)")
print(f"  sample shared terms: {sorted(inter)[:15]}")
print(f"  sample KG-only terms: {sorted(kg_comps - jira_comps)[:15]}")
print(f"  sample gold-only terms: {sorted(jira_comps - kg_comps)[:15]}")

# ---- C. Per-ticket: does the KG extraction reproduce that ticket's own Jira components? ----
kg_by_id = {}
with open(f"{G}/v2_kg_extractions/all_extractions.jsonl", encoding="utf-8") as f:
    for line in f:
        d = json.loads(line)
        kg_by_id[d["ticket_id"]] = {c.strip().lower() for c in (d.get("components") or [])}

# memory corpus row -> its jira components
hit, tot = 0, 0
with open(f"{G}/jira-memory-corpus.jsonl", encoding="utf-8") as f:
    first = json.loads(f.readline())
print(f"\n  memory-corpus row keys: {list(first.keys())[:25]}")

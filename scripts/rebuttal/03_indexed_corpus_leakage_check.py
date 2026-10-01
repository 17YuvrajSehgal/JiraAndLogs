import json, random, re, sys
sys.path.insert(0, "C:/workplace/JiraAndLogs/src")
from memorygraph.humanized_loader import load_humanized_corpus
from pathlib import Path
G = Path("C:/workplace/JiraAndLogs/data/derived/global/2026-06-17-wol-real-v3-global")

mem = load_humanized_corpus(G, humanized_subdir="bulk-20260617",
                            humanized_root="jira-shadow-humanized-v2")
print("fields on JiraMemoryIssue:", [f for f in vars(mem[0])][:30])

# legacy corpus: episode -> wol_source_id
ep2src = {}
with open(G/"jira-memory-corpus.jsonl", encoding="utf-8") as f:
    for line in f:
        d = json.loads(line)
        ep2src[d.get("incident_episode_id")] = d.get("wol_source_id")
src2comp = {}
with open(G/"global-triage-examples.jsonl", encoding="utf-8") as f:
    for line in f:
        d = json.loads(line)
        if d.get("wol_source_id"):
            src2comp[d["wol_source_id"]] = list(d.get("triage_components") or [])

def wb(c, txt):
    return re.search(r"(?<![a-z0-9])"+re.escape(c.strip().lower())+r"(?![a-z0-9])", txt) is not None

random.seed(42); sample = random.sample(mem, 4000)
docs = docs_with = tot = wbh = 0
for m in sample:
    src = ep2src.get(m.incident_episode_id)
    comps = src2comp.get(src) or []
    if not comps: continue
    txt = ((m.memory_text or "") + " " + (m.resolution_notes or "")).lower()
    docs += 1
    h = sum(1 for c in comps if wb(c, txt))
    tot += len(comps); wbh += h
    if h: docs_with += 1
print(f"\n=== INDEXED (humanized) memory — gold-component visibility ===")
print(f"docs with >=1 Jira gold component: {docs}")
print(f"  ...mentioning >=1 of its own gold component name: {docs_with} ({docs_with/max(1,docs)*100:.1f}%)")
print(f"  gold component-name recall in indexed text: {wbh}/{tot} = {wbh/max(1,tot)*100:.1f}%")
print("\n(compare: legacy jira-memory-corpus.jsonl memory_text = 100.0%, which is NOT what was indexed)")

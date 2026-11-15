# LocAgent: Graph-Guided LLM Agents for Code Localization

**Zhaoling Chen, Xiangru Tang, Gangda Deng, Fang Wu, Jialong Wu, Zhiwei Jiang, Viktor Prasanna, Arman Cohan, Xingyao Wang (Yale/USC/Stanford/All Hands AI). ACL 2025 (arXiv 2503.09089).**
PDF: `pdfs/locagent-acl2025.pdf` · Code: github.com/gersteinlab/LocAgent

## What it is

Code localization (files → modules → functions) as a graph-guided agent:
the codebase is parsed (Python AST) into a heterogeneous directed graph
(nodes: dirs/files/classes/functions; edges: contain, invoke, import,
inherit), with a sparse hierarchical ENTITY INDEX (qualified-name index →
name dictionary → BM25 inverted index → chunk-to-entity map). The agent
gets exactly three tools: SearchEntity, TraverseGraph (type-aware BFS with
hop control — "one action = multi-hop navigation"), RetrieveEntity. CoT
plan: keywords → link to entities → reconstruct fault-to-failure flow →
emit locations; confidence by aggregating reciprocal ranks across sampled
iterations. They also fine-tune Qwen2.5-7B/32B on 433 Claude-3.5
trajectories (+335 self-improvement) to cut cost ~86%.

## Numbers and what they mean

SWE-bench Lite (274 usable; STRICT metric — ALL gold locations must be in
top-k; file/module/function):
- BM25: file Acc@1 38.7 / Acc@5 61.7 — the "retrieval floor".
- Best embedding (CodeRankEmbed): 52.6 / 84.7.
- Agentless (Claude-3.5): 72.6 / 79.6 (file Acc@1/@5).
- SWE-agent 77.4/90.2; OpenHands 76.3/90.2.
- **LocAgent Claude-3.5: 77.7 / 94.2 file; 86.5 module@5; 73.4
  function@5. Fine-tuned Qwen-32B nearly matches (75.9/92.7) at ~$0.05–
  0.20 per example.**
- Loc-Bench (their new 560-issue post-Oct-2024 Python set incl. security/
  performance issues, built to dodge contamination): everything drops —
  LocAgent Claude-3.5 file Acc@5 83.4, function Acc@10 59.3; Agentless
  falls to 67.5. (MULocBench later shows even steeper drops.) The agent >
  procedure > embedding > BM25 ordering persists.
- Ablations: removing TraverseGraph or the sparse index hurts most;
  restricting to 1 hop hurts function-level accuracy — multi-hop
  structure matters, directory structure alone does not.
- Hop analysis: performance decays with "hops" between the issue-mentioned
  entities and the gold location; agents degrade more gracefully than
  retrieval — THE LLM-side mirror of our easy/hard stratum (hop 0 ≈ easy).

## Relevance to us

- The modern reference points for what agents achieve at file level with
  full repo access on Python: ~78% Acc@1 (contaminated Lite) vs ~59–83%
  on fresh data. Useful when positioning our CPU-only 0.794 acc@5 (Kafka)
  with no LLM and no training.
- Their STRICT all-locations metric is worth adopting as a secondary
  number (we report any-gold Acc@K; strict Acc@K is computable from our
  per-instance data for free and preempts a reviewer ask).
- Their graph tools presuppose Python AST machinery; porting to C++ is
  the same tree-sitter lift our function-level stage needs (W4) — cite as
  the design to emulate at region level if we add it.
- Module-level reporting precedent (their module Acc@K) matches our
  module output — good company for Table 3.

## Weaknesses / notes

- Python-only; "module" means class-ish granularity, not top-level
  component as ours does — define clearly when comparing.
- Fine-tuning data comes from Claude trajectories on SWE-bench-adjacent
  repos — the contamination question partially recurses into the
  fine-tune.
- Strict metric on ≤5-file patches only (they filter >5 files / >10
  functions from Loc-Bench) — population trimmed toward tractable issues.
- No history/memory signal; no time-awareness.

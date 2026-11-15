# Long Code Arena: a Set of Benchmarks for Long-Context Code Models (bug-localization task)

**JetBrains Research. arXiv 2406.11612 (2024).** Dataset: huggingface.co/datasets/JetBrains-Research/lca-bug-localization
PDF: `pdfs/longcodearena-2024.pdf` (read: the Bug Localization task section; the suite has 6 tasks — we only need this one)

## The bug-localization task

Given a GitHub bug issue + the repository snapshot where the bug is
reproducible, identify the files the fix modified. Construction: 8M issues
/ 7M PRs → regex-linked ("fixes #24") → quality filters → 7,479 bug-issue/
PR pairs (4,339 Python, 2,522 Java, 618 Kotlin) → **manually validated 150
instances (50 per language, most-starred repos first), balanced half
single-file / half 2–10-file fixes**. Median repo 331 files; issues ~400
tokens.

## Baselines and numbers (their MAP)

TF-IDF (BPE) 0.27; CodeT5/CodeBERT embeddings <0.25; GTE 0.33; Mistral
embeddings 0.30; BM25 (llama-index) lower; GPT-3.5 and **GPT-4 prompted
over the file list: 0.39 MAP** (chunked prompting when the list overflows
context). So on manually-vetted GitHub bug issues, the gap between
general-purpose embeddings (0.33) and GPT-4-with-full-file-list (0.39) is
modest — more evidence that LLM gains over decent retrieval are small
without repo navigation (contrast LocAgent's agent gains).

## Relevance to us

- One of the two "three parts reliably, logs sometimes" datasets (with
  SWE-bench) that constrain our benchmark-first claim (§2): it has issue +
  snapshot + gold files; log presence incidental. 150 evaluated instances
  vs our 6,437.
- Their balanced single-vs-multi-file sampling is a design worth citing
  when we report gold-size distribution (our median 1, mean 1.7–3.1).
- Metric note: they report P@k/R@k with k conditioned on gold size (k=1
  for single-file, k=2 for multi) — an alternative to our fixed-K that a
  reviewer might ask about; our strict-Acc@K (LocAgent-style) answers the
  same concern more conventionally.

## Weaknesses / notes

- 150 instances after manual curation; most-starred-first selection biases
  toward well-maintained repos.
- Regex PR-issue linking (same class as our subject-key linkage, GitHub
  flavor); no time-awareness; no history signal.
- The suite's other tasks (module summarization etc.) are irrelevant to
  us; its CompScore LLM-judge metric is interesting but out of scope.

## Use in our paper

- §2 benchmark-claim narrowing (with Pathidea and SWE-bench) and the
  comparative dataset table if we include one.

# Bug-Report–Driven Fault Localization: Industrial Benchmarking and Lessons Learned at ABB Robotics

**Pernilla Hall, Anton Ununger (ABB Robotics), Riccardo Rubei, Alessio Bucaioni (Mälardalen U). EASE 2026 (arXiv 2604.25700v2).**
PDF: `pdfs/abb-industrial-bl-2026.pdf`

## What it is

The closest INDUSTRY-TRACK precedent to our submission's genre: five years
of proprietary ABB Robotics bug reports linked to verified fixes, used for
TEXT-ONLY fault localization (no source code, traces, or repo access at
inference), framed as supervised multi-label classification at the
SUBFOLDER/COMPONENT level. Pipeline: closed bugs → commit-linked →
modified paths → mapped to subfolders → diffuse fixes and rare labels
filtered → **660 reports, 31 component labels, mean 1.56 labels/report**
(1,867 before filtering). Models: LR/SVM/RF with TF-IDF (+ sentence
embeddings) vs fine-tuned RoBERTa-Base/Distil-RoBERTa, with
class-imbalance-aware augmentation; metrics Top-k Acc, Recall@k, MAP, MRR.

## Findings

- **TF-IDF + classical models beat fine-tuned transformers** on this
  industrial data: LR best MRR/Top-1; RF (with augmentation) best
  MAP/Recall@1; SVM best Top-5 without augmentation. Distil-RoBERTa
  generalized better than RoBERTa-Base; neither consistently beat TF-IDF.
- Explicit motivations matching ours: confidentiality forbids cloud LLM
  APIs; auxiliary artifacts (traces, call graphs) "rarely hold in
  industrial maintenance contexts"; public-corpus LLM evaluations risk
  pretraining overlap; label distribution is Pareto (five subfolders
  dominate — their world's version of our memory concentration premise).

## Relevance to us

- **Genre validator**: an industrial venue accepted text-only,
  lexical-first localization with ranking metrics and honest
  "simple beats transformer" findings — exactly our paper's disposition
  (CPU-only BM25 signals, honest negatives).
- Their component level ≈ our module level; 31 labels for one system vs
  our per-project module spaces — cite when defending module-level
  reporting as the industrially actionable granularity.
- Contrast to draw: they TRAIN a supervised classifier per system
  (needs labeled history + retraining); our memory signal uses the same
  history **without training** and yields file-level output. Also no
  temporal discipline is described for their split — worth checking
  before citing beyond genre support.
- Related-work nuggets with numbers usable as context: co-fix PageRank
  Top-10 32–41% (Chen et al.); LaProb Top-1 14–68%; Gharibi multi-source
  Top-1 ≈52%; AutoFL Top-1 29–53% — the field's realistic ranges, far
  from SWE-bench Lite euphoria.

## Weaknesses / notes

- Single proprietary system; 660 instances after heavy filtering (rare
  labels removed — survivors are the easy, frequent components; they
  acknowledge imbalance but the filtering inflates attainable scores).
- Subfolder-level only; no file/function output; no IRBL baselines like
  BugLocator run on their data (classification framing, not retrieval).
- Augmentation details and split hygiene (random vs temporal) matter and
  are under-specified in what we read — do not cite its numbers as
  comparable to ours, only the design lessons.

## Use in our paper

- Related work (industrial): one sentence as the industrial-constraints
  precedent (text-only, local, lightweight wins), positioning our work as
  the retrieval/memory counterpart that adds file-level output and a
  temporal firewall without supervised training.

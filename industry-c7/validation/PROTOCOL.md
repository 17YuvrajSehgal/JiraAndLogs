# Gold-validation protocol

200 instances (50 per project, seed 42, drawn from the full benchmark).
Each rater fills their own TSV independently; do not discuss instances
before both sheets are complete.

Open `issue_url` and every `commit_urls` entry, then answer:

- **Q1_link_ok** - `y` if the commit(s) clearly fix THIS issue (the
  commit message, diff, or linked review makes it evident); `n` if the
  link is wrong (unrelated change, wrong ticket); `unsure` otherwise.
- **Q2_gold_kind** - `root` if the listed gold files contain the code
  that CAUSED the failure; `repair` if they only contain a workaround or
  a guard somewhere else (the cause lives in a file not listed);
  `unsure` otherwise. Answer only when Q1 is `y`.
- **notes** - optional free text.

When both sheets are filled, run:
    python industry-c7/scripts/score_validation.py

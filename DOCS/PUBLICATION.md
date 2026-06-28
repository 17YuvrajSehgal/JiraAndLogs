# Publication plan — datasets & large artifacts

The git repo carries **code + all metrics/summaries** (`paper-results/**/*.json`,
`*.md`). It deliberately excludes large binaries (gitignored): the datasets
(`data/`), per-window predictions (`*-predictions.jsonl`), agent traces
(`paper-results/**/traces/`), and ablation per-cell reports. These ship as a
**release archive** alongside the repo (Zenodo / Figshare / institutional store),
cross-linked by DOI.

## What goes where
| Artifact | Size (raw) | Channel |
|---|---|---|
| Code + metrics + summaries + docs | small | **git repo** (this) |
| `online-boutique` dataset | ~215 MB | release archive |
| `otel-demo` dataset | ~31 MB | release archive |
| `wol-v3` dataset (real Apache Jira) | ~5 GB | release archive |
| `paper-results` predictions + traces | ~3.3 GB | release archive |

## Build the archives
```bash
bash scripts/research-lab/make_release_archives.sh /scratch/$USER/release
```
Produces, in the target dir: `dataset-online-boutique.tar.zst`,
`dataset-otel-demo.tar.zst`, `dataset-wol-v3.tar.zst`,
`paper-results-predictions-traces.tar.zst`, and `SHA256SUMS.txt`.

## Hosting checklist (for camera-ready)
1. Upload the archives to Zenodo; mint a DOI.
2. Add `CITATION.cff` + the DOI badge to `README.md`.
3. Record the dataset license (**CC BY 4.0**) + Apache-Jira source attribution
   (already in `DOCS/WoL-v3-dataset.md`) in the Zenodo metadata.
4. Verify a clean checkout + `pip install --no-index` + one `trillium_*.sbatch`
   reproduces a `paper-results/**/SUMMARY.md` row from the archived dataset.

## Ethics / licensing note
WoL is derived from **public** Apache Jira issues across 24 open-source projects
(no private data, no PII beyond public committer handles already on the public
tracker). Released CC BY 4.0 as a derived dataset; see `DOCS/WoL-v3-dataset.md`.

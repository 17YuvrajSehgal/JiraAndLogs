# Trillium Cluster — Quick Instructions

This project runs on the **Trillium** HPC cluster (University of Toronto / SciNet,
operated under the Digital Research Alliance of Canada).

- **Official docs:** https://docs.alliancecan.ca/wiki/Trillium_Quickstart
- **Running jobs:** https://docs.alliancecan.ca/wiki/Running_jobs
- **SciNet docs:** https://docs.scinet.utoronto.ca

> When in doubt about a command or limit, check the Alliance/SciNet docs above —
> they are authoritative. The values below are confirmed for this account.

---

## This account / environment (confirmed)

| Thing | Value |
|---|---|
| CPU login nodes | `tri-login01` … `tri-login06` |
| **GPU login node** | **`trig-login01`** — ssh here to see/submit GPU jobs |
| User | `yuvraj17` |
| `$HOME` | `/home/yuvraj17` (backed up, **read-only on compute nodes**, small quota) |
| `$SCRATCH` | `/scratch/yuvraj17` (large, **not backed up**, purged; shared across all login nodes) |
| Project allocation | none (`$PROJECT` not available) |
| Slurm account | `def-naser2` (pass via `--account=def-naser2`) |
| Cluster env var | `$CC_CLUSTER = trillium` |

**Work lives in `$SCRATCH`.** This repo is at
`/scratch/yuvraj17/JiraAndLogs_scratch/JiraAndLogs`. Datasets under `data/` are
large (10s of GB) — keep them on scratch, never home.

> **GPUs are only visible from `trig-login01`.** From the CPU login nodes
> (`tri-login0X`) `sinfo` shows `Gres=(null)` everywhere — no GPUs. To run a GPU
> job: `ssh trig-login01` first, then `sbatch`. The filesystem is shared, so your
> venv / data / images are identical there.

---

## Hardware (per node)

- **CPU node** (`compute` from `tri-login0X`): 2 × 96-core AMD EPYC "Zen5" =
  **192 cores**, 767 GiB RAM.
- **GPU node** (`trig####`, `compute`/`debug` from `trig-login01`): 96-core EPYC
  "Zen4" + **4 × NVIDIA H100 80 GB** + 745 GiB RAM.

The GPU `compute` partition allows **shared, per-GPU** jobs (request
`--gpus-per-node=1` → you get ~24 cores + 186 GiB). `compute_full_node` is
exclusive (whole node, 4 GPUs, 96 cores).

---

## Golden rules

1. **Never run heavy work on a login node.** Logins are for editing, git, small
   scripts, pulling images, and submitting jobs only. Long training / embedding /
   KG-extraction runs go through Slurm.
2. **Walltime:** min **15 min**, max **24 h** per job.
3. **Always pass `--account=def-naser2`.**
4. `$HOME` is read-only on compute nodes → write all job output to `$SCRATCH`.
5. **Do NOT use `--mem`** — it is forbidden on Trillium (sbatch errors out).
   Per-GPU jobs auto-get 186 GiB; whole-node jobs get 745 GiB.
6. **No Docker** — use **Apptainer**. Compute nodes have **no internet**:
   pre-pull images / pre-cache HuggingFace models on a login node, then run jobs
   with `HF_HUB_OFFLINE=1`. Pulling a `.sif` on the login node segfaults in
   `mksquashfs`; build a **`--sandbox` dir** instead. Always run server
   containers (e.g. Neo4j) with `apptainer run --cleanenv …` so host env vars
   don't leak into the container.

---

## Common commands

```bash
# Software (Lmod)
module avail                 # list modules
module spider <name>         # search for a module + how to load it
module load python/3.12      # load a module (then activate your venv)

# Submit / monitor
sbatch job.sh                # submit a batch script
squeue -u $USER              # my queued/running jobs
squeue --start -j <JOBID>    # estimated start time
scancel <JOBID>              # cancel a job
sacct -j <JOBID>             # job history / exit codes
seff <JOBID>                 # efficiency (CPU/mem used vs requested)

# Interactive session (debug/dev) — request a node, then run interactively
salloc --account=def-naser2 --nodes=1 --time=1:00:00
```

---

## Example batch script

CPU job (full 192-core node):

```bash
#!/bin/bash
#SBATCH --account=def-naser2
#SBATCH --job-name=wol-cascade
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=192
#SBATCH --time=12:00:00
#SBATCH --output=%x-%j.out

cd /scratch/yuvraj17/JiraAndLogs_scratch/JiraAndLogs
module load python/3.12
source .venv/bin/activate
python scripts/research-lab/run_bm25_wol_mode3.py --global-dir data/derived/global/2026-06-17-wol-real-v3-global
```

GPU job — request GPUs with `--gpus-per-node=N` (NO `--mem`):

```bash
#SBATCH --partition=compute
#SBATCH --nodes=1
#SBATCH --gpus-per-node=1
#SBATCH --cpus-per-task=24
#SBATCH --time=08:00:00
```

Submit with `sbatch <script>.sh`, watch with `squeue -u $USER`.

---

## WoL v3 Hybrid-RRF run on Trillium (this project)

One-time setup already done: a venv at `.venv` (Alliance wheelhouse +
`neo4j`), HuggingFace models pre-cached at `/scratch/$USER/hf_cache`, and a
Neo4j Apptainer **sandbox** at `/scratch/$USER/apptainer/neo4j-sandbox`.

**Run it (from `trig-login01`):**

```bash
ssh trig-login01                       # GPU login node
cd /scratch/$USER/JiraAndLogs_scratch/JiraAndLogs
sbatch scripts/research-lab/trillium_hybrid_rrf.sbatch
```

The job (`scripts/research-lab/trillium_hybrid_rrf.sbatch`):
1. starts Neo4j via `deploy/research-lab/neo4j_apptainer.sh` (Apptainer),
2. reloads the v3 KG graph into the `neo4j` DB (~50 min, skipped if already
   loaded — set `RELOAD_GRAPH=1` to force),
3. runs the Hybrid-RRF cascade (SPLADE + BiEncoder + graph, RRF fusion) on 1×H100.

**Key cluster adaptations baked in:** offline HuggingFace (`HF_HUB_OFFLINE=1`);
the BM25 hard-negative mining is parallelised across all allocated cores via
`BIENC_BM25_JOBS` (the step that ran ~20 h single-threaded locally — proven
bit-identical to serial); Neo4j runs with `apptainer run --cleanenv`.

**Watch live progress (a single combined log, updated continuously):**

```bash
tail -f logs/v3_hybrid_rrf.log          # stable symlink to the latest job's log
squeue -u $USER                         # job state
```

Outputs land in
`data/derived/global/2026-06-17-wol-real-v3-global/tch-lite-refit/`:
`hybrid-rrf-predictions.jsonl` + `hybrid-rrf-mode3-results.json`.

For maximum BM25 cores, edit the sbatch to `--partition=compute_full_node`
`--cpus-per-task=96` (whole node, 4 GPUs).

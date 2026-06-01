"""Training-run registry — organized model + log + config storage.

When a pipeline trains and evaluates, it writes everything for that
run under a single directory:

    data/derived/global/<global_id>/training_runs/<run_id>/
        config.json          # pipeline name, hyperparams, corpus paths, git SHA
        metrics.json         # PR-AUC / Recall@5 / MRR / per-strata / bootstrap CIs
        predictions.jsonl    # per-window predictions for downstream re-scoring
        train.log            # human-readable training log
        model/               # pickled fitted estimators (if applicable)
            model.pkl
            ...
        artifacts/           # pipeline-specific extras (graph stats, etc.)

`run_id` is `<pipeline_name>__<UTC YYYYMMDDTHHMMSSZ>__<sha8>` so re-runs
of the same pipeline don't collide and the run is self-describing.

Provides a `TrainingRun` context manager that returns the directory and
helpers for writing each artifact type. Idempotent: re-entering a run
with the same id appends to logs and overwrites artifacts.

Used by:
  * `scripts/research-lab/train_pipeline.py` — single-pipeline driver
  * `comparison/runner.py` — multi-pipeline leaderboard (optional flag)

Lightweight — stdlib only, no sklearn/torch dependency. Pickling is
opt-in by passing an object to `run.save_model(name, obj)`.
"""

from __future__ import annotations

import datetime
import hashlib
import io
import json
import os
import pickle
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator


def _git_sha(short: int = 8) -> str:
    """Read the current git HEAD SHA; returns 'unknown' on failure."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(Path(__file__).resolve().parent.parent.parent),
            capture_output=True, text=True, timeout=2,
        )
        if result.returncode == 0:
            return result.stdout.strip()[:short]
    except (subprocess.SubprocessError, OSError, FileNotFoundError):
        pass
    return "unknown"


def make_run_id(pipeline_name: str, *, when: datetime.datetime | None = None) -> str:
    """Return a self-describing run id: <pipeline>__<UTCstamp>__<sha8>.

    Stable when `when` is provided (useful for tests / re-runs).
    """
    when = when or datetime.datetime.now(datetime.timezone.utc)
    stamp = when.strftime("%Y%m%dT%H%M%SZ")
    sha = _git_sha()
    safe = "".join(c if (c.isalnum() or c in "-_") else "-" for c in pipeline_name)
    return f"{safe}__{stamp}__{sha}"


@dataclass
class TrainingRun:
    """One training-run directory + its artifact-writing helpers."""

    run_id: str
    run_dir: Path
    pipeline_name: str
    started_at: str
    log_lines: list[str] = field(default_factory=list)
    _log_fh: Any = None

    # ----- Sub-paths
    @property
    def config_path(self) -> Path:
        return self.run_dir / "config.json"

    @property
    def metrics_path(self) -> Path:
        return self.run_dir / "metrics.json"

    @property
    def predictions_path(self) -> Path:
        return self.run_dir / "predictions.jsonl"

    @property
    def log_path(self) -> Path:
        return self.run_dir / "train.log"

    @property
    def model_dir(self) -> Path:
        return self.run_dir / "model"

    @property
    def artifacts_dir(self) -> Path:
        return self.run_dir / "artifacts"

    # ----- Writers
    def write_config(self, config: dict[str, Any]) -> None:
        """Write the run-level config. Always called once at the top of
        a run so a reviewer knows what was trained."""
        full = {
            "run_id": self.run_id,
            "pipeline_name": self.pipeline_name,
            "started_at": self.started_at,
            "git_sha": _git_sha(short=40),
            "python_version": sys.version,
            **config,
        }
        self.config_path.write_text(
            json.dumps(full, indent=2, default=str), encoding="utf-8",
        )

    def write_metrics(self, metrics: dict[str, Any]) -> None:
        """Write the final headline + stratified metrics."""
        full = {
            "run_id": self.run_id,
            "pipeline_name": self.pipeline_name,
            "completed_at": datetime.datetime.now(
                datetime.timezone.utc
            ).isoformat(),
            **metrics,
        }
        self.metrics_path.write_text(
            json.dumps(full, indent=2, default=str), encoding="utf-8",
        )

    def append_prediction(self, row: dict[str, Any]) -> None:
        """One JSONL line per scored window. Caller controls when to
        flush (typically at end of `predict_split`)."""
        line = json.dumps(row, default=str) + "\n"
        with self.predictions_path.open("a", encoding="utf-8") as fh:
            fh.write(line)

    def log(self, msg: str) -> None:
        """Add a human-readable line to train.log AND echo to stderr."""
        stamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        line = f"[{stamp}] {msg}"
        self.log_lines.append(line)
        print(line, file=sys.stderr)
        if self._log_fh is not None:
            self._log_fh.write(line + "\n")
            self._log_fh.flush()

    def save_model(self, name: str, obj: Any) -> Path:
        """Pickle an arbitrary fitted estimator to model/<name>.pkl.
        Caller is responsible for objects being picklable.

        Returns the absolute path written.
        """
        self.model_dir.mkdir(parents=True, exist_ok=True)
        out = self.model_dir / f"{name}.pkl"
        with out.open("wb") as fh:
            pickle.dump(obj, fh, protocol=pickle.HIGHEST_PROTOCOL)
        self.log(f"saved model: {out.relative_to(self.run_dir)} ({out.stat().st_size} bytes)")
        return out

    def save_artifact(self, name: str, content: bytes | str | dict) -> Path:
        """Write a pipeline-specific extra (graph stats, embedding-cache
        summary, distractor confusion matrix, etc.) under artifacts/."""
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        out = self.artifacts_dir / name
        if isinstance(content, dict):
            out.write_text(json.dumps(content, indent=2, default=str), encoding="utf-8")
        elif isinstance(content, str):
            out.write_text(content, encoding="utf-8")
        else:
            out.write_bytes(content)
        self.log(f"saved artifact: {out.relative_to(self.run_dir)}")
        return out

    def load_model(self, name: str) -> Any:
        """Re-load a previously-saved estimator for re-scoring without
        re-training."""
        p = self.model_dir / f"{name}.pkl"
        with p.open("rb") as fh:
            return pickle.load(fh)


@contextmanager
def open_training_run(
    *,
    global_dir: Path,
    pipeline_name: str,
    run_id: str | None = None,
    notes: str = "",
) -> Iterator[TrainingRun]:
    """Context manager: create the run dir, open the log, return a
    TrainingRun. On exit, close the log fh.

    Usage:
        with open_training_run(global_dir=..., pipeline_name="hgb") as run:
            run.write_config({"max_depth": 8, ...})
            run.log("starting fit ...")
            run.save_model("clf", fitted_estimator)
            run.write_metrics({"pr_auc": 0.66, ...})
    """
    global_dir = Path(global_dir)
    started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    rid = run_id or make_run_id(pipeline_name)
    run_dir = global_dir / "training_runs" / rid
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "model").mkdir(exist_ok=True)
    (run_dir / "artifacts").mkdir(exist_ok=True)

    log_path = run_dir / "train.log"
    log_fh = log_path.open("a", encoding="utf-8")
    run = TrainingRun(
        run_id=rid,
        run_dir=run_dir,
        pipeline_name=pipeline_name,
        started_at=started_at,
        _log_fh=log_fh,
    )
    if notes:
        run.log(f"notes: {notes}")
    run.log(f"training_run open: {rid}")
    try:
        yield run
    finally:
        run.log(f"training_run close: {rid}")
        log_fh.close()


def list_training_runs(global_dir: Path) -> list[dict[str, Any]]:
    """Return a list of completed training runs under a global_dir,
    sorted by started_at descending. Each entry is the run's
    config.json + a peek at metrics.json.
    """
    root = Path(global_dir) / "training_runs"
    if not root.exists():
        return []
    out: list[dict[str, Any]] = []
    for rd in sorted(root.iterdir(), reverse=True):
        if not rd.is_dir():
            continue
        cfg_path = rd / "config.json"
        if not cfg_path.exists():
            continue
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        metrics_path = rd / "metrics.json"
        metrics_peek: dict[str, Any] = {}
        if metrics_path.exists():
            try:
                m = json.loads(metrics_path.read_text(encoding="utf-8"))
                metrics_peek = {
                    k: m.get(k)
                    for k in ("pr_auc_strict", "recall_at_5", "mrr",
                              "completed_at")
                    if k in m
                }
            except (json.JSONDecodeError, OSError):
                pass
        out.append({
            "run_id": cfg.get("run_id", rd.name),
            "pipeline_name": cfg.get("pipeline_name", "?"),
            "started_at": cfg.get("started_at"),
            "git_sha": cfg.get("git_sha", "")[:8],
            "metrics_peek": metrics_peek,
            "run_dir": str(rd),
        })
    return out


if __name__ == "__main__":
    # Smoke
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--global-dir", required=True)
    p.add_argument("--action", default="list", choices=["list", "smoke"])
    args = p.parse_args()
    if args.action == "list":
        for run in list_training_runs(Path(args.global_dir)):
            peek = run.get("metrics_peek", {})
            print(
                f"{run['run_id']:60s} "
                f"PR-AUC={peek.get('pr_auc_strict', '?')} "
                f"R@5={peek.get('recall_at_5', '?')} "
                f"MRR={peek.get('mrr', '?')}"
            )
    elif args.action == "smoke":
        with open_training_run(
            global_dir=Path(args.global_dir), pipeline_name="_smoke",
        ) as run:
            run.write_config({"smoke": True, "purpose": "registry test"})
            run.log("hello from smoke")
            run.append_prediction({"window_id": "w-1", "score": 0.42})
            run.write_metrics({"pr_auc_strict": 0.5, "n_windows": 1})
        print(f"smoke run wrote: {run.run_dir}")

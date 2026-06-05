"""Tiny GPU utilization monitor.

Used by Phase G training scripts to verify the RTX 5060 is actually
being utilized during fine-tuning. Writes a JSONL trace of GPU stats
that can be plotted post-hoc and included in the ICSE paper's
reproducibility appendix.
"""
from __future__ import annotations

import json
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional


def _query_nvidia_smi() -> Optional[dict]:
    """Run nvidia-smi --query-gpu=... once and return parsed metrics."""
    try:
        out = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu="
                "timestamp,index,name,utilization.gpu,utilization.memory,"
                "memory.used,memory.total,temperature.gpu,power.draw",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode != 0:
            return None
        # Take first GPU only
        line = out.stdout.strip().splitlines()[0]
        parts = [p.strip() for p in line.split(",")]
        return {
            "ts": parts[0],
            "gpu_index": int(parts[1]),
            "name": parts[2],
            "util_gpu_pct": float(parts[3]),
            "util_mem_pct": float(parts[4]),
            "mem_used_mib": float(parts[5]),
            "mem_total_mib": float(parts[6]),
            "temp_c": float(parts[7]),
            "power_w": float(parts[8]),
            "wall_s": time.time(),
        }
    except (subprocess.SubprocessError, OSError, FileNotFoundError, ValueError, IndexError):
        return None


class GPUMonitor:
    """Background thread that samples nvidia-smi every `interval_s` seconds
    and appends one JSON line to the given path.

    Usage:
        with GPUMonitor(Path("results/gpu.jsonl"), interval_s=2.0, tag="ft"):
            train()
    """

    def __init__(
        self,
        out_path: Path,
        *,
        interval_s: float = 2.0,
        tag: str = "",
    ) -> None:
        self.out_path = Path(out_path)
        self.interval_s = interval_s
        self.tag = tag
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False

    def start(self) -> None:
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

    def _run(self) -> None:
        with self.out_path.open("a", encoding="utf-8") as fh:
            # Stamp a start record
            start = _query_nvidia_smi() or {}
            start["event"] = "start"
            start["tag"] = self.tag
            fh.write(json.dumps(start) + "\n")
            fh.flush()
            while not self._stop_event.is_set():
                row = _query_nvidia_smi()
                if row is not None:
                    row["tag"] = self.tag
                    fh.write(json.dumps(row) + "\n")
                    fh.flush()
                self._stop_event.wait(timeout=self.interval_s)
            stop = _query_nvidia_smi() or {}
            stop["event"] = "stop"
            stop["tag"] = self.tag
            fh.write(json.dumps(stop) + "\n")


def summarize(path: Path) -> dict:
    """One-line summary: avg/p95/max GPU util, mem usage, temp, power."""
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            try:
                row = json.loads(line)
                if "util_gpu_pct" in row:
                    rows.append(row)
            except json.JSONDecodeError:
                continue
    if not rows:
        return {}

    def _pct(values, q):
        s = sorted(values)
        idx = max(0, min(len(s) - 1, int(round(q * (len(s) - 1)))))
        return s[idx]

    utils = [r["util_gpu_pct"] for r in rows]
    mems = [r["mem_used_mib"] for r in rows]
    return {
        "n_samples": len(rows),
        "duration_s": rows[-1]["wall_s"] - rows[0]["wall_s"],
        "gpu_util_mean": sum(utils) / len(utils),
        "gpu_util_p95": _pct(utils, 0.95),
        "gpu_util_max": max(utils),
        "mem_used_mib_mean": sum(mems) / len(mems),
        "mem_used_mib_max": max(mems),
        "temp_c_max": max(r["temp_c"] for r in rows),
        "power_w_mean": sum(r["power_w"] for r in rows) / len(rows),
        "power_w_max": max(r["power_w"] for r in rows),
    }

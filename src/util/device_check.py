"""CLI: report whether the in-Python GPU stack is reachable.

    python -m util.device_check

Prints a one-line short status and (if not GPU-ready) a fix hint.
Exits 0 when GPU is reachable, 1 otherwise — so it composes with
shell-level checks (`python -m util.device_check && pipeline.py ...`).
"""

from __future__ import annotations

import sys

from .device import gpu_status


_INSTALL_HINT = """
To enable in-Python GPU on this box (RTX 5060 / Blackwell sm_120):

  1. Uninstall the CPU-only torch wheel currently in the venv:
       .venv\\Scripts\\pip uninstall -y torch

  2. Install a CUDA-enabled torch built against CUDA 12.8 or newer
     (Blackwell requires sm_120 kernels which only ship in CUDA 12.8+):
       .venv\\Scripts\\pip install --pre torch --index-url \\
         https://download.pytorch.org/whl/nightly/cu128

     (Stable wheels for CUDA 12.8 may not yet exist for Python 3.14 —
      if `pip install torch --index-url https://download.pytorch.org/whl/cu128`
      fails, the nightly index above is the fallback.)

  3. For xgboost-GPU on tabular features:
       .venv\\Scripts\\pip install xgboost

  4. Re-run this check:
       .venv\\Scripts\\python -m util.device_check

LM Studio (Qwen + Nomic) is GPU-accelerated independently — it manages
its own CUDA runtime. With ~7 GB already used by LM Studio on an 8 GB
card, leave headroom: the pipelines pick batch sizes from free VRAM via
safe_batch_size(), but you may need to unload an LM Studio model before
running a heavy bi-encoder sweep.
""".strip()


def main() -> int:
    status = gpu_status()
    print(status.short())
    print()
    print(f"  torch:           {status.torch_version or '(not installed)'}")
    print(f"  cuda build:      {status.torch_cuda_build or '(CPU-only wheel)'}")
    print(f"  cuda available:  {status.cuda_available}")
    if status.compute_capability:
        cap = status.compute_capability
        print(f"  compute cap:     sm_{cap[0]}{cap[1]}")
    if status.free_vram_bytes is not None and status.total_vram_bytes is not None:
        free_gb = status.free_vram_bytes / 1e9
        total_gb = status.total_vram_bytes / 1e9
        print(f"  vram:            {free_gb:.2f} GB free / {total_gb:.2f} GB total")
    print(f"  diagnosis:       {status.reason}")
    if status.device == "cuda":
        return 0
    print()
    print(_INSTALL_HINT)
    return 1


if __name__ == "__main__":
    sys.exit(main())

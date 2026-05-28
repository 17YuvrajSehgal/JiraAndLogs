"""GPU device detection + status reporting for ML/AI pipelines.

One place to ask "should I run on GPU or CPU?". All neural code in this
repo (sentence-transformers, future cross-encoders) should call
`resolve_device()` rather than passing 'cpu' or 'cuda' literals around.

Why a helper instead of `torch.cuda.is_available()` everywhere:
  * The venv may have the CPU-only torch build (`torch.version.cuda is None`)
    even when nvidia-smi reports a usable GPU. `is_available()` returns
    False in that case with no hint why — we surface the diagnosis.
  * RTX 5060 / Blackwell needs CUDA 12.8+ torch. An older CUDA torch wheel
    will load but fail at runtime with "no kernel image for this device".
    `gpu_status_report()` checks compute capability so we fail loud at
    pipeline start instead of mid-encode.
  * LM Studio holds ~7GB of the 8GB on this box. A second process needs
    to share — surface free VRAM so pipelines can pick batch sizes
    that don't OOM.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any, Literal


DeviceStr = Literal["cuda", "cpu"]


@dataclass(frozen=True)
class GpuStatus:
    """What the GPU-detection probe found.

    `device` is what callers should use. The rest is diagnostic.
    """

    device: DeviceStr
    torch_installed: bool
    torch_version: str | None
    torch_cuda_build: str | None  # e.g. "12.8" — None for the CPU-only wheel
    cuda_available: bool
    device_name: str | None
    compute_capability: tuple[int, int] | None  # (major, minor); Blackwell = (12, 0)
    free_vram_bytes: int | None
    total_vram_bytes: int | None
    reason: str  # human-readable explanation for the resolved device choice

    def short(self) -> str:
        if self.device == "cuda" and self.device_name:
            free_gb = (self.free_vram_bytes or 0) / 1e9
            total_gb = (self.total_vram_bytes or 0) / 1e9
            return (
                f"GPU: {self.device_name} (sm_{self.compute_capability[0]}{self.compute_capability[1]}, "
                f"{free_gb:.1f}/{total_gb:.1f} GB free)"
            )
        return f"CPU ({self.reason})"


def _probe() -> GpuStatus:
    try:
        import torch  # type: ignore
    except ImportError:
        return GpuStatus(
            device="cpu",
            torch_installed=False,
            torch_version=None,
            torch_cuda_build=None,
            cuda_available=False,
            device_name=None,
            compute_capability=None,
            free_vram_bytes=None,
            total_vram_bytes=None,
            reason="torch not installed",
        )

    torch_version = getattr(torch, "__version__", "?")
    torch_cuda_build = getattr(getattr(torch, "version", None), "cuda", None)

    if torch_cuda_build is None:
        return GpuStatus(
            device="cpu",
            torch_installed=True,
            torch_version=torch_version,
            torch_cuda_build=None,
            cuda_available=False,
            device_name=None,
            compute_capability=None,
            free_vram_bytes=None,
            total_vram_bytes=None,
            reason=f"CPU-only torch wheel installed ({torch_version}); reinstall with CUDA support",
        )

    try:
        cuda_available = bool(torch.cuda.is_available())
    except Exception as exc:
        return GpuStatus(
            device="cpu",
            torch_installed=True,
            torch_version=torch_version,
            torch_cuda_build=torch_cuda_build,
            cuda_available=False,
            device_name=None,
            compute_capability=None,
            free_vram_bytes=None,
            total_vram_bytes=None,
            reason=f"torch.cuda probe raised: {exc!r}",
        )

    if not cuda_available:
        return GpuStatus(
            device="cpu",
            torch_installed=True,
            torch_version=torch_version,
            torch_cuda_build=torch_cuda_build,
            cuda_available=False,
            device_name=None,
            compute_capability=None,
            free_vram_bytes=None,
            total_vram_bytes=None,
            reason=f"torch {torch_version} (CUDA {torch_cuda_build}) loaded but no CUDA device visible",
        )

    try:
        name = torch.cuda.get_device_name(0)
        cap = tuple(torch.cuda.get_device_capability(0))  # (major, minor)
        free, total = torch.cuda.mem_get_info(0)
    except Exception as exc:
        return GpuStatus(
            device="cpu",
            torch_installed=True,
            torch_version=torch_version,
            torch_cuda_build=torch_cuda_build,
            cuda_available=False,
            device_name=None,
            compute_capability=None,
            free_vram_bytes=None,
            total_vram_bytes=None,
            reason=f"GPU info probe raised: {exc!r}",
        )

    # Sanity-fire a tiny matmul — catches "no kernel image for this device"
    # (compute-capability/torch-build mismatch) before pipelines try real work.
    try:
        a = torch.zeros((4, 4), device="cuda")
        _ = a @ a
        torch.cuda.synchronize()
    except Exception as exc:
        return GpuStatus(
            device="cpu",
            torch_installed=True,
            torch_version=torch_version,
            torch_cuda_build=torch_cuda_build,
            cuda_available=False,
            device_name=name,
            compute_capability=cap,
            free_vram_bytes=free,
            total_vram_bytes=total,
            reason=(
                f"GPU detected ({name}, sm_{cap[0]}{cap[1]}) but kernel launch failed: {exc!r}. "
                f"For Blackwell (sm_120) you need torch built against CUDA 12.8+."
            ),
        )

    return GpuStatus(
        device="cuda",
        torch_installed=True,
        torch_version=torch_version,
        torch_cuda_build=torch_cuda_build,
        cuda_available=True,
        device_name=name,
        compute_capability=cap,
        free_vram_bytes=free,
        total_vram_bytes=total,
        reason="CUDA reachable + kernel launch verified",
    )


_cached_status: GpuStatus | None = None


def gpu_status() -> GpuStatus:
    """Return the cached probe result. First call runs the probe."""
    global _cached_status
    if _cached_status is None:
        _cached_status = _probe()
    return _cached_status


def resolve_device(
    *,
    prefer: DeviceStr | None = None,
    log_to: Any = sys.stderr,
) -> DeviceStr:
    """Pick the device a pipeline should run on.

    `prefer="cpu"` forces CPU even if GPU is available (useful for tests
    and for sharing the box with LM Studio when VRAM is tight).
    `prefer="cuda"` raises if GPU isn't usable — call sites that say
    `prefer="cuda"` are declaring "GPU is required for this run."
    Default (`prefer=None`) is "use GPU when available, fall back silently".
    """
    status = gpu_status()
    if prefer == "cpu":
        if log_to is not None:
            print(f"[device] using CPU (forced by caller)", file=log_to)
        return "cpu"
    if prefer == "cuda" and status.device != "cuda":
        raise RuntimeError(f"GPU required but unavailable: {status.reason}")
    if log_to is not None:
        print(f"[device] {status.short()}", file=log_to)
    return status.device


def safe_batch_size(
    *,
    bytes_per_item: int,
    default_cpu: int = 32,
    default_gpu: int = 256,
    headroom_fraction: float = 0.5,
) -> int:
    """Pick a batch size that fits in the free VRAM (or fall back to default).

    `bytes_per_item` is a rough upper bound per encoded item including
    activations. For sentence-transformers MiniLM at 512 tokens this is
    ~150 KB; for a 6-layer cross-encoder it's ~1 MB.
    """
    status = gpu_status()
    if status.device == "cpu":
        return default_cpu
    free = status.free_vram_bytes or 0
    budget = int(free * headroom_fraction)
    fit = max(1, budget // max(bytes_per_item, 1))
    return min(default_gpu, fit)

"""Portable, deterministic hardware and dependency inspection."""

from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import subprocess
import sys
from typing import Any


def detect_hardware() -> dict[str, Any]:
    machine = platform.machine().lower()
    system = platform.system().lower()
    memory_bytes = None
    if system == "darwin":
        try:
            out = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True, timeout=2)
            memory_bytes = int(out.strip())
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    elif system == "linux":
        try:
            with open("/proc/meminfo", encoding="utf-8") as meminfo:
                for line in meminfo:
                    if line.startswith("MemTotal:"):
                        memory_bytes = int(line.split()[1]) * 1024
                        break
        except OSError:
            pass
    memory_gb = round(memory_bytes / 1024**3, 1) if memory_bytes else None
    mps = system == "darwin" and machine in {"arm64", "aarch64"}
    cuda = False
    torch_available = importlib.util.find_spec("torch") is not None
    if torch_available:
        try:
            import torch

            mps = bool(torch.backends.mps.is_available()) if hasattr(torch.backends, "mps") else mps
            cuda = bool(torch.cuda.is_available())
        except Exception:
            pass
    ffmpeg = shutil.which("ffmpeg")
    ffmpeg_version = None
    if ffmpeg:
        try:
            output = subprocess.run([ffmpeg, "-version"], capture_output=True, text=True, timeout=2, check=False).stdout.splitlines()
            ffmpeg_version = output[0] if output else None
        except (OSError, subprocess.SubprocessError):
            pass
    cpu = platform.processor() or platform.machine()
    if system == "darwin":
        try:
            cpu = subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"], text=True, timeout=2).strip() or cpu
        except (OSError, subprocess.SubprocessError):
            pass
    onnx_providers = []
    if importlib.util.find_spec("onnxruntime") is not None:
        try:
            import onnxruntime

            onnx_providers = list(onnxruntime.get_available_providers())
        except Exception:
            pass
    cuda_visible = os.environ.get("CUDA_VISIBLE_DEVICES", "").strip()
    return {
        "os": f"{platform.system()} {platform.release()}",
        "architecture": machine or platform.machine(),
        "python": platform.python_version(),
        "cpu": cpu,
        "memory_gb": memory_gb,
        "metal": mps,
        "mps": mps,
        "cuda": cuda or bool(cuda_visible and cuda_visible != "-1"),
        "torch": torch_available,
        "ffmpeg": bool(ffmpeg),
        "ffmpeg_version": ffmpeg_version,
        "onnxruntime": importlib.util.find_spec("onnxruntime") is not None,
        "onnx_providers": onnx_providers,
        "supported_target": system == "darwin" and machine in {"arm64", "aarch64"},
    }


def target_id(hardware: dict[str, Any] | None = None) -> str:
    """Return the registry platform identifier for the current host."""
    hardware = hardware or detect_hardware()
    system = str(hardware.get("os", "")).split(" ", 1)[0].lower()
    architecture = str(hardware.get("architecture", "")).lower()
    normalized = "arm64" if architecture in {"arm64", "aarch64"} else "x64" if architecture in {"x86_64", "amd64", "x64"} else architecture
    return {"darwin": f"macos-{normalized}", "linux": f"linux-{normalized}", "windows": f"windows-{normalized}"}.get(system, f"{system}-{normalized}")


def recommended_model(spec, hardware=None) -> str:
    hardware = hardware or detect_hardware()
    memory = hardware.get("memory_gb") or 8
    if spec.name == "vision.detect":
        return "yolo11s" if memory >= 16 else "yolo11n"
    if spec.name == "vision.depth":
        return "depth-anything-v2-small" if memory < 32 else "depth-anything-v2-base"
    if spec.name == "vision.segment":
        return "sam2-small"
    return spec.model

"""Isolated provider environments managed by uv (or stdlib venv fallback)."""

from __future__ import annotations

import json
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path


class EnvironmentError(RuntimeError):
    pass


PROVIDER_REQUIREMENTS = {
    "ultralytics": ["ultralytics"],
    "paddleocr": ["paddleocr", "paddlepaddle"],
    "torch": ["torch"],
    "transformers": ["transformers", "Pillow", "torch"],
    "silero-vad": ["silero-vad", "torch"],
    "mineru": ["mineru"],
    "omniparser": [],
}

PROVIDER_IMPORTS = {
    "ultralytics": ["ultralytics"],
    "paddleocr": ["paddleocr"],
    "torch": ["torch"],
    "transformers": ["transformers", "PIL", "torch"],
    "silero-vad": ["silero_vad", "torch"],
    "mineru": ["magic_pdf"],
}

REQUIREMENT_IMPORTS = {
    "paddlepaddle": "paddle",
    "Pillow": "PIL",
    "silero-vad": "silero_vad",
    "mineru": "magic_pdf",
}


class ProviderEnvironmentManager:
    def __init__(self, cache, timeout_seconds=1800):
        self.cache = cache
        self.timeout_seconds = timeout_seconds

    def path(self, provider: str) -> Path:
        return self.cache.environments / provider.replace("/", "__").replace(".", "__")

    def python(self, provider: str) -> Path:
        root = self.path(provider)
        candidate = root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        return candidate

    def status(self, provider: str) -> dict:
        root = self.path(provider)
        marker = root / "specialist-environment.json"
        if not marker.exists() or not self.python(provider).exists():
            return {"provider": provider, "status": "not installed", "path": str(root)}
        try:
            value = json.loads(marker.read_text(encoding="utf-8"))
            if value.get("provider") != provider or value.get("python") != str(self.python(provider)):
                return {"provider": provider, "status": "corrupt", "path": str(root), "message": "environment metadata does not match its path"}
            return value
        except (OSError, ValueError):
            return {"provider": provider, "status": "corrupt", "path": str(root)}

    def ensure(self, provider: str, requirements: list[str] | None = None) -> dict:
        existing = self.status(provider)
        requirements = PROVIDER_REQUIREMENTS.get(provider, [provider]) if requirements is None else list(requirements)
        if existing.get("status") == "ready" and existing.get("requirements") == requirements and self.verify(provider, requirements):
            return existing
        root = self.path(provider)
        root.parent.mkdir(parents=True, exist_ok=True)
        if root.exists():
            shutil.rmtree(root)
        uv = shutil.which("uv")
        if uv:
            self._run([uv, "venv", "--python", sys.executable, str(root)])
            python = self.python(provider)
            if requirements:
                self._run([uv, "pip", "install", "--python", str(python), *requirements])
        else:
            self._run([sys.executable, "-m", "venv", str(root)])
            if requirements:
                self._run([str(self.python(provider)), "-m", "pip", "install", *requirements])
        if not self.verify(provider, requirements):
            raise EnvironmentError(f"provider environment '{provider}' was created but imports are not usable")
        metadata = {"provider": provider, "status": "ready", "path": str(root), "python": str(self.python(provider)), "python_version": f"{sys.version_info.major}.{sys.version_info.minor}", "requirements": requirements, "requirements_sha256": hashlib.sha256(json.dumps(requirements, separators=(",", ":")).encode()).hexdigest()}
        marker = root / "specialist-environment.json"
        self.cache._atomic_write(marker, json.dumps(metadata, indent=2) + "\n")
        return metadata

    def verify(self, provider: str, requirements: list[str] | None = None) -> bool:
        python = self.python(provider)
        if not python.exists():
            return False
        modules = PROVIDER_IMPORTS.get(provider)
        if modules is None:
            modules = [REQUIREMENT_IMPORTS.get(requirement, requirement.replace("-", "_")) for requirement in (requirements or [])]
        if not modules:
            return True
        probe = "import importlib.util, sys; missing=[m for m in %r if importlib.util.find_spec(m) is None]; sys.exit(1 if missing else 0)" % modules
        try:
            completed = subprocess.run([str(python), "-c", probe], capture_output=True, text=True, timeout=30, check=False)
        except (OSError, subprocess.SubprocessError):
            return False
        return completed.returncode == 0

    def remove(self, provider: str) -> bool:
        root = self.path(provider)
        if not root.exists():
            return False
        shutil.rmtree(root)
        return True

    def _run(self, command):
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=self.timeout_seconds, check=False)
        except subprocess.TimeoutExpired as exc:
            raise EnvironmentError(f"provider environment command timed out: {' '.join(command[:3])}") from exc
        if completed.returncode:
            detail = (completed.stderr or completed.stdout).strip()[-3000:]
            raise EnvironmentError(f"provider environment command failed ({completed.returncode}): {detail}")

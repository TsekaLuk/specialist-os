"""Isolated provider environments managed by uv (or stdlib venv fallback)."""

from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


class EnvironmentError(RuntimeError):
    pass


PROVIDER_REQUIREMENTS = {
    "ace_step": ["ace-step @ git+https://github.com/ace-step/ACE-Step-1.5.git@ca1e85fe9430179831e6bc6be790c332190a3866"],
    "basic_pitch": ["basic-pitch[onnx]==0.4.0", "setuptools==80.9.0"],
    "essentia": ["essentia==2.1b6.dev1389"],
    "muscriptor": ["muscriptor==0.3.0", "pretty-midi==0.2.11", "soundfile==0.14.0"],
    "audio_separator": ["audio-separator[cpu]==0.30.2"],
    "rosvot": ["torch==2.2.2", "torchaudio==2.2.2", "numpy==1.26.4", "librosa==0.10.2.post1", "pretty-midi==0.2.11", "pyworld==0.3.5", "setuptools==80.9.0", "matplotlib==3.11.1", "pyyaml==6.0.3", "einops==0.8.2", "pyloudnorm==0.2.0", "tqdm==4.67.3"],
    # Keep provider environments reproducible and aligned with the artifact
    # formats recorded in registry/models.yaml. These versions are tested on
    # the supported Python 3.12 macOS/Linux matrix.
    "ultralytics": ["ultralytics==8.3.0"],
    "paddleocr": ["paddleocr==3.7.0", "paddlepaddle==3.3.1"],
    "torch": ["torch==2.14.0"],
    "transformers": ["transformers==4.57.3", "Pillow==12.3.0", "torch==2.14.0"],
    "silero-vad": ["silero-vad==6.2.1", "torch==2.14.0"],
    "mineru": ["mineru[pipeline]==3.4.5", "torch==2.8.0", "torchvision==0.23.0", "transformers==4.57.3", "six==1.17.0"],
    "omniparser": [
        "ultralytics==8.3.70",
        "transformers==4.49.0",
        "Pillow==12.3.0",
        "torch==2.8.0",
        "torchvision==0.23.0",
        "timm==1.0.20",
        "einops==0.8.0",
        "paddleocr==3.7.0",
        "paddlepaddle==3.3.1",
    ],
    "mediapipe": ["mediapipe==0.10.21"],
    "pyannote.audio": ["pyannote.audio==4.0.7", "torch==2.8.0", "torchaudio==2.8.0", "torchcodec==0.7.0", "soundfile==0.13.1"],
    "deepfilternet": ["DeepFilterNet==0.5.6", "torch==2.4.1", "torchaudio==2.4.1", "soundfile==0.13.1"],
    "open_clip": ["open_clip_torch==2.31.0", "Pillow==12.3.0", "torch==2.4.1", "socksio==1.0.0", "transformers==4.57.3", "sentencepiece==0.2.0"],
    "insightface": ["insightface==0.7.3", "onnxruntime==1.19.2"],
    "opencv": ["opencv-python-headless==4.10.0.84"],
}

PROVIDER_IMPORTS = {
    "ace_step": ["acestep", "torch", "soundfile"],
    "basic_pitch": ["basic_pitch", "onnxruntime", "pretty_midi"],
    "essentia": ["essentia"],
    "muscriptor": ["muscriptor", "pretty_midi", "soundfile"],
    "audio_separator": ["audio_separator", "onnxruntime", "soundfile"],
    "rosvot": ["torch", "librosa", "pyworld", "pretty_midi", "yaml", "einops", "tqdm"],
    "ultralytics": ["ultralytics"],
    "paddleocr": ["paddleocr"],
    "torch": ["torch"],
    "transformers": ["transformers", "PIL", "torch"],
    "silero-vad": ["silero_vad", "torch"],
    "mineru": ["mineru", "torch", "torchvision", "transformers", "six"],
    "omniparser": ["ultralytics", "transformers", "torch", "torchvision", "paddleocr", "paddle", "PIL"],
    "mediapipe": ["mediapipe"],
    "pyannote.audio": ["pyannote", "torch", "soundfile"],
    "deepfilternet": ["df", "torch", "torchaudio", "soundfile"],
    "open_clip": ["open_clip", "PIL", "torch", "socksio", "transformers", "sentencepiece"],
    "insightface": ["insightface"],
    "opencv": ["cv2"],
}

REQUIREMENT_IMPORTS = {
    "paddlepaddle": "paddle",
    "Pillow": "PIL",
    "silero-vad": "silero_vad",
    "mineru": "mineru",
    "opencv-python-headless": "cv2",
    "open_clip_torch": "open_clip",
    "DeepFilterNet": "df",
}

PROVIDER_PYTHON = {"basic_pitch": "3.11", "audio_separator": "3.11", "muscriptor": "3.12", "rosvot": "3.11", "ace_step": "3.11"}


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
        uv = shutil.which("uv")
        host_python = f"{sys.version_info.major}.{sys.version_info.minor}"
        if not uv and provider in PROVIDER_PYTHON and host_python != PROVIDER_PYTHON[provider]:
            raise EnvironmentError(f"{provider} requires Python {PROVIDER_PYTHON[provider]}; install uv to manage its interpreter")
        root = self.path(provider)
        root.parent.mkdir(parents=True, exist_ok=True)
        if root.exists():
            shutil.rmtree(root)
        if uv:
            self._run([uv, "venv", "--python", PROVIDER_PYTHON.get(provider, sys.executable), str(root)])
            python = self.python(provider)
            if requirements:
                self._run([uv, "pip", "install", "--python", str(python), *requirements])
        else:
            self._run([sys.executable, "-m", "venv", str(root)])
            if requirements:
                self._run([str(self.python(provider)), "-m", "pip", "install", *requirements])
        if not self.verify(provider, requirements):
            raise EnvironmentError(f"provider environment '{provider}' was created but imports are not usable")
        metadata = {"provider": provider, "status": "ready", "path": str(root), "python": str(self.python(provider)), "python_version": PROVIDER_PYTHON.get(provider, host_python), "requirements": requirements, "requirements_sha256": hashlib.sha256(json.dumps(requirements, separators=(",", ":")).encode()).hexdigest()}
        marker = root / "specialist-environment.json"
        self.cache._atomic_write(marker, json.dumps(metadata, indent=2) + "\n")
        return metadata

    def verify(self, provider: str, requirements: list[str] | None = None) -> bool:
        python = self.python(provider)
        if not python.exists():
            return False
        modules = PROVIDER_IMPORTS.get(provider)
        if modules is None:
            names = [re.split(r"[\[<>=!~; @]", requirement, maxsplit=1)[0] for requirement in (requirements or [])]
            modules = [REQUIREMENT_IMPORTS.get(name, name.replace("-", "_")) for name in names]
        if not modules:
            return True
        required_python = PROVIDER_PYTHON.get(provider)
        probe = ("import importlib.util, sys; missing=[m for m in %r if importlib.util.find_spec(m) is None]; "
                 "required=%r; valid=required is None or '.'.join(map(str, sys.version_info[:2])) == required; "
                 "sys.exit(1 if missing or not valid else 0)") % (modules, required_python)
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

    def install_artifact(self, provider: str, artifact: Path) -> dict:
        """Install a locally verified provider wheel into its isolated env."""
        python = self.python(provider)
        if not python.exists() or not artifact.is_file() or artifact.suffix != ".whl":
            raise EnvironmentError(f"provider artifact is not an installable wheel: {artifact}")
        uv = shutil.which("uv")
        command = [uv, "pip", "install", "--python", str(python), str(artifact)] if uv else [str(python), "-m", "pip", "install", str(artifact)]
        self._run(command)
        return {"status": "installed", "provider": provider, "artifact": str(artifact), "python": str(python)}

    def _run(self, command):
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=self.timeout_seconds, check=False)
        except subprocess.TimeoutExpired as exc:
            raise EnvironmentError(f"provider environment command timed out: {' '.join(command[:3])}") from exc
        if completed.returncode:
            detail = (completed.stderr or completed.stdout).strip()[-3000:]
            raise EnvironmentError(f"provider environment command failed ({completed.returncode}): {detail}")

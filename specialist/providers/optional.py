"""Optional production provider adapters.

Imports are lazy so installing the core never pulls in PyTorch or model
weights. Each adapter normalizes its upstream output into the stable schemas.
"""

from __future__ import annotations

import importlib
import array
import json
import shutil
import subprocess
import wave
from collections.abc import Mapping
from pathlib import Path

from .ipc import WorkerError


def _missing(package):
    raise WorkerError(f"optional dependency '{package}' is not installed; install it in the provider environment with `specialist --with-dependencies install <capability>`", code="dependency_missing", retryable=False)


class OptionalProvider:
    requires_verified_artifact = True
    supported_platforms = ("macos-arm64", "linux-x64", "windows-x64")
    supported_devices = ("cpu", "mps", "cuda")
    memory_requirement_mb = 1024
    disk_requirement_mb = 512
    license = "provider terms"

    def __init__(self, name, capability, model):
        self.name = name
        self.capability = capability
        self.model = model
        self._loaded = False
        self._allow_unverified_models = False

    def install(self, cache, spec):
        self._check_dependency()
        self._cache = cache
        model = getattr(self, "model", None) or spec.model
        cache.mark_installed(spec.name, spec.provider, model, status="available", license_name=spec.license, source="optional-provider", commercial=getattr(spec, "commercial", None), source_url=getattr(spec, "source_url", None))
        return {"status": "available", "downloaded": False, "backend": "optional", "note": "weights are downloaded lazily by the upstream provider; use a verified artifact to disable implicit downloads"}

    def doctor(self, hardware):
        try:
            self._check_dependency()
        except WorkerError as exc:
            return {"status": "not ready", "backend": "optional", "error": {"code": exc.code, "message": str(exc)}}
        return {"status": "ready", "backend": "optional", "hardware": hardware}

    def load(self):
        if not self._loaded:
            cache = getattr(self, "_cache", None)
            installation = cache.installation(self.capability) if cache and hasattr(cache, "installation") else None
            if not self._allow_unverified_models and not (installation and installation.get("artifact_path") and installation.get("sha256")):
                raise WorkerError("a verified model artifact is required; install with --source and --sha256 or explicitly allow provider downloads", code="model_artifact_required", retryable=False)
            self._load_model()
            self._loaded = True
        return self

    def unload(self):
        self._loaded = False

    def _check_dependency(self):
        raise NotImplementedError

    def _load_model(self):
        return None


class YOLOProvider(OptionalProvider):
    def __init__(self, capability="vision.detect", model="yolo11n"):
        super().__init__("yolo", capability, model)

    def _check_dependency(self):
        if importlib.util.find_spec("ultralytics") is None:
            _missing("ultralytics")

    def _load_model(self):
        self._check_dependency()
        from ultralytics import YOLO

        model_ref = self.model
        artifact = getattr(self, "_cache", None)
        if artifact:
            candidate = artifact.models / self.capability.replace(".", "__") / self.model
            if candidate.is_file():
                model_ref = str(candidate)
        self._model = YOLO(model_ref)

    def infer(self, input_path, options, cache):
        self.load()
        outputs = self._model.predict(source=str(input_path), verbose=False, device=options.get("device"))
        items = []
        for output in outputs:
            boxes = getattr(output, "boxes", None)
            if boxes is None:
                continue
            coordinates = boxes.xyxy.cpu().tolist()
            confidence = boxes.conf.cpu().tolist()
            labels = boxes.cls.cpu().tolist()
            names = getattr(output, "names", {})
            for bbox, score, label in zip(coordinates, confidence, labels):
                items.append({"label": names.get(int(label), str(int(label))), "bbox": [round(float(v), 2) for v in bbox], "confidence": round(float(score), 6)})
        return {"items": items}, []


class UltralyticsSegmentProvider(OptionalProvider):
    def __init__(self, model="sam2_s.pt"):
        super().__init__("sam", "vision.segment", model)

    def _check_dependency(self):
        if importlib.util.find_spec("ultralytics") is None:
            _missing("ultralytics")

    def _load_model(self):
        self._check_dependency()
        from ultralytics import SAM

        model_ref = {"sam2-small": "sam2_s.pt"}.get(self.model, self.model)
        artifact = getattr(self, "_cache", None)
        if artifact:
            candidate = artifact.models / self.capability.replace(".", "__") / self.model
            if candidate.is_file():
                model_ref = str(candidate)
        self._model = SAM(model_ref)

    def infer(self, input_path, options, cache):
        self.load()
        kwargs = {}
        if options.get("bbox"):
            kwargs["bboxes"] = [options["bbox"]]
        elif options.get("point"):
            kwargs["points"] = [options["point"]]
            kwargs["labels"] = [1]
        elif options.get("prompt"):
            raise WorkerError("SAM requires a point or bbox prompt; text prompts need a grounding provider", code="prompt_not_supported", retryable=False)
        outputs = self._model(str(input_path), verbose=False, **kwargs)
        masks = []
        for output in outputs:
            polygons = getattr(getattr(output, "masks", None), "xy", []) or []
            for polygon in polygons:
                masks.append({"polygon": polygon.tolist() if hasattr(polygon, "tolist") else polygon})
        return {"masks": masks, "prompt": options.get("prompt") or options.get("bbox") or options.get("point")}, []


class PaddleOCRProvider(OptionalProvider):
    def __init__(self, model="pp-ocrv5-mobile"):
        super().__init__("paddleocr", "vision.ocr", model)

    def _check_dependency(self):
        if importlib.util.find_spec("paddleocr") is None:
            _missing("paddleocr")
        if importlib.util.find_spec("paddle") is None:
            _missing("paddlepaddle")

    def _load_model(self):
        self._check_dependency()
        from paddleocr import PaddleOCR

        self._model = PaddleOCR()

    def infer(self, input_path, options, cache):
        self.load()
        raw = self._model.predict(str(input_path)) if hasattr(self._model, "predict") else self._model.ocr(str(input_path), cls=True)
        blocks = []
        for page in raw or []:
            if isinstance(page, Mapping) or hasattr(page, "get"):
                texts = page.get("rec_texts", [])
                scores = page.get("rec_scores", [])
                polygons = page.get("rec_polys", [])
                texts = [] if texts is None else texts
                scores = [] if scores is None else scores
                polygons = [] if polygons is None else polygons
                for index, text in enumerate(texts):
                    polygon = polygons[index].tolist() if index < len(polygons) and hasattr(polygons[index], "tolist") else (polygons[index] if index < len(polygons) else [])
                    xs = [point[0] for point in polygon] if polygon else [0]
                    ys = [point[1] for point in polygon] if polygon else [0]
                    blocks.append({"text": str(text), "bbox": [min(xs), min(ys), max(xs), max(ys)], "confidence": float(scores[index]) if index < len(scores) else None})
            else:
                for line in page or []:
                    if len(line) >= 2:
                        polygon, value = line[0], line[1]
                        text, score = value if isinstance(value, (list, tuple)) else (str(value), None)
                        xs = [point[0] for point in polygon]
                        ys = [point[1] for point in polygon]
                        blocks.append({"text": str(text), "bbox": [min(xs), min(ys), max(xs), max(ys)], "confidence": score})
        return {"blocks": blocks}, []


class TransformersDepthProvider(OptionalProvider):
    def __init__(self, model="depth-anything/Depth-Anything-V2-Small-hf"):
        super().__init__("depth-anything", "vision.depth", model)

    def _check_dependency(self):
        if importlib.util.find_spec("transformers") is None:
            _missing("transformers")
        if importlib.util.find_spec("PIL") is None:
            _missing("Pillow")
        if importlib.util.find_spec("torch") is None:
            _missing("torch")

    def _load_model(self):
        self._check_dependency()
        from transformers import pipeline

        model_ref = {"depth-anything-v2-small": "depth-anything/Depth-Anything-V2-Small-hf", "depth-anything-v2-base": "depth-anything/Depth-Anything-V2-Base-hf"}.get(self.model, self.model)
        artifact = getattr(self, "_cache", None)
        if artifact:
            candidate = artifact.models / self.capability.replace(".", "__") / self.model
            if candidate.exists():
                model_ref = str(candidate)
        self._pipeline = pipeline("depth-estimation", model=model_ref, cache_dir=str(self._cache.models) if getattr(self, "_cache", None) else None)

    def infer(self, input_path, options, cache):
        self.load()
        from PIL import Image

        output = self._pipeline(Image.open(input_path))
        preview = cache.results / f"{cache.input_hash(input_path)[:16]}-depth.png"
        cache.ensure_dirs()
        output["depth"].save(preview)
        width, height = output["depth"].size
        return {"width": width, "height": height, "depth_map": None, "preview": str(preview), "mode": "relative"}, []


class SileroVADProvider(OptionalProvider):
    def __init__(self, model="silero-vad-v5"):
        super().__init__("silero-vad", "audio.vad", model)

    def _check_dependency(self):
        if importlib.util.find_spec("silero_vad") is None:
            _missing("silero-vad")
        if importlib.util.find_spec("torch") is None:
            _missing("torch")

    def _load_model(self):
        self._check_dependency()
        from silero_vad import load_silero_vad

        self._model = load_silero_vad()

    def infer(self, input_path, options, cache):
        self.load()
        import torch
        from silero_vad import get_speech_timestamps

        with wave.open(str(input_path), "rb") as audio:
            sample_rate = audio.getframerate()
            frames = audio.readframes(audio.getnframes())
            channels = audio.getnchannels()
            width = audio.getsampwidth()
        if width != 2:
            raise WorkerError("Silero VAD currently requires 16-bit PCM WAV", code="unsupported_audio_format", retryable=False)
        samples = array.array("h", frames)
        if channels > 1:
            samples = array.array("h", [sum(samples[index:index + channels]) // channels for index in range(0, len(samples), channels)])
        tensor = torch.tensor(samples, dtype=torch.float32) / 32768.0
        raw = get_speech_timestamps(tensor, self._model, sampling_rate=sample_rate, return_seconds=True)
        segments = [{"start": float(item["start"]), "end": float(item["end"])} for item in raw]
        return {"segments": segments, "duration_seconds": len(samples) / float(sample_rate or 1)}, []


class CommandDocumentProvider(OptionalProvider):
    """Adapter for MinerU-compatible CLI commands configured in the environment."""

    def __init__(self, command="magic-pdf", model="mineru-2"):
        super().__init__("mineru", "document.parse", model)
        self.command = command

    def _check_dependency(self):
        if shutil.which(self.command) is None:
            _missing(self.command)

    def infer(self, input_path, options, cache):
        self._check_dependency()
        output_dir = cache.results / f"document-{cache.input_hash(input_path)[:16]}"
        output_dir.mkdir(parents=True, exist_ok=True)
        try:
            completed = subprocess.run([self.command, "-p", str(input_path), "-o", str(output_dir)], capture_output=True, text=True, timeout=float(options.get("timeout_seconds", 900)), check=False)
        except subprocess.TimeoutExpired as exc:
            raise WorkerError("document parser timed out", code="provider_timeout") from exc
        if completed.returncode:
            raise WorkerError(completed.stderr.strip()[-2000:] or "document parser failed", code="provider_error", retryable=True)
        markdown_files = sorted(output_dir.rglob("*.md"))
        markdown = markdown_files[0].read_text(encoding="utf-8") if markdown_files else completed.stdout.strip()
        return {"markdown": markdown, "pages": None, "tables": [], "figures": [], "formulas": [], "artifacts_path": str(output_dir)}, []


class CommandScreenProvider(OptionalProvider):
    """Adapter for an OmniParser-compatible JSON CLI."""

    def __init__(self, command="omniparser", model="omniparser-v2"):
        super().__init__("omniparser", "screen.parse", model)
        self.command = command

    def _check_dependency(self):
        if shutil.which(self.command) is None:
            _missing(self.command)

    def infer(self, input_path, options, cache):
        self._check_dependency()
        try:
            completed = subprocess.run([self.command, str(input_path), "--json"], capture_output=True, text=True, timeout=float(options.get("timeout_seconds", 120)), check=False)
        except subprocess.TimeoutExpired as exc:
            raise WorkerError("screen parser timed out", code="provider_timeout") from exc
        if completed.returncode:
            raise WorkerError(completed.stderr.strip()[-2000:] or "screen parser failed", code="provider_error", retryable=True)
        try:
            parsed = json.loads(completed.stdout)
        except ValueError as exc:
            raise WorkerError("screen parser returned invalid JSON", code="worker_invalid_output", retryable=False) from exc
        elements = parsed.get("elements", []) if isinstance(parsed, dict) else (parsed if isinstance(parsed, list) else [])
        return {"elements": elements}, []


class WhisperCppProvider(OptionalProvider):
    def __init__(self, binary="whisper-cli", model="ggml-base.en.bin"):
        super().__init__("whisper.cpp", "audio.transcribe", model)
        self.binary = binary

    def _check_dependency(self):
        import shutil

        if shutil.which(self.binary) is None:
            _missing(self.binary)

    def infer(self, input_path, options, cache):
        self._check_dependency()
        model_path = self.model
        installation = cache.installation(self.capability) if hasattr(cache, "installation") else None
        if installation and installation.get("artifact_path"):
            model_path = installation["artifact_path"]
        command = [self.binary, "-m", model_path, "-f", str(input_path), "--output-json"]
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=float(options.get("timeout_seconds", 300)), check=False)
        except subprocess.TimeoutExpired as exc:
            raise WorkerError("whisper.cpp timed out", code="provider_timeout") from exc
        if completed.returncode:
            raise WorkerError(completed.stderr.strip()[-2000:] or "whisper.cpp failed", code="provider_error", retryable=True)
        candidates = [Path(str(input_path) + ".json"), input_path.with_suffix(".json")]
        parsed = None
        for candidate in candidates:
            if candidate.is_file():
                try:
                    parsed = json.loads(candidate.read_text(encoding="utf-8"))
                    break
                except (OSError, ValueError):
                    continue
        if parsed is None:
            try:
                parsed = json.loads(completed.stdout.strip()) if completed.stdout.strip() else {}
            except ValueError as exc:
                raise WorkerError("whisper.cpp returned invalid JSON", code="provider_invalid_output", retryable=False) from exc
        if not isinstance(parsed, dict):
            raise WorkerError("whisper.cpp returned a JSON value instead of an object", code="provider_invalid_output", retryable=False)
        raw_segments = parsed.get("segments") or parsed.get("transcription") or []
        segments = []
        for item in raw_segments:
            if not isinstance(item, dict):
                continue
            timestamps = item.get("timestamps") or {}
            segments.append({"start": item.get("start", timestamps.get("from")), "end": item.get("end", timestamps.get("to")), "text": str(item.get("text", "")).strip()})
        text = parsed.get("text") or " ".join(item["text"] for item in segments if item["text"]).strip()
        return {"text": str(text), "segments": segments}, []

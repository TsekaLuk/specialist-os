"""Optional production provider adapters.

Imports are lazy so installing the core never pulls in PyTorch or model
weights. Each adapter normalizes its upstream output into the stable schemas.
"""

from __future__ import annotations

import importlib
import array
import json
import os
import shutil
import subprocess
import wave
from collections.abc import Mapping
from pathlib import Path

from .ipc import WorkerError
from ..models import ModelManager, ModelArtifactError


def _missing(package):
    raise WorkerError(f"optional dependency '{package}' is not installed; install it in the provider environment with `specialist --with-dependencies install <capability>`", code="dependency_missing", retryable=False)


def _run_external(command, *, timeout, env=None):
    """Run a provider command and terminate its whole process group on timeout."""
    kwargs = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "text": True, "env": env}
    if os.name == "posix":
        kwargs["start_new_session"] = True
    process = subprocess.Popen(command, **kwargs)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            if os.name == "posix":
                import signal

                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
            process.wait(timeout=0.5)
        except (OSError, subprocess.TimeoutExpired):
            try:
                if os.name == "posix":
                    import signal

                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            except OSError:
                pass
        process.communicate()
        raise
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


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
            if installation and installation.get("artifact_path") and not self._allow_unverified_models:
                try:
                    manager = ModelManager(cache)
                    if installation.get("artifact_kind") == "bundle":
                        verified = manager.verify_bundle(Path(installation["artifact_path"]), Path(installation.get("artifact_manifest") or Path(installation["artifact_path"]) / "artifact-manifest.json"))
                        if installation.get("sha256") and verified.get("manifest_sha256") != installation.get("sha256"):
                            raise ModelArtifactError("bundle manifest identity does not match installation metadata")
                    else:
                        manager.verify(Path(installation["artifact_path"]), installation.get("sha256"))
                except (ModelArtifactError, OSError, ValueError) as exc:
                    raise WorkerError(f"verified model artifact failed integrity check: {exc}", code="model_artifact_corrupt", retryable=False) from exc
            self._load_model()
            self._loaded = True
        return self

    def unload(self):
        self._loaded = False

    def _check_dependency(self):
        raise NotImplementedError

    def _load_model(self):
        return None

    def artifact_path(self):
        """Return the verified file or bundle entrypoint for this provider."""
        cache = getattr(self, "_cache", None)
        installation = cache.installation(self.capability) if cache and hasattr(cache, "installation") else None
        if not installation or not installation.get("artifact_path"):
            return None
        root = Path(installation["artifact_path"])
        if installation.get("artifact_kind") == "bundle":
            entrypoint = installation.get("artifact_entrypoint")
            if entrypoint:
                return root / entrypoint
            return root
        return root

    def artifact_root(self):
        cache = getattr(self, "_cache", None)
        installation = cache.installation(self.capability) if cache and hasattr(cache, "installation") else None
        if installation and installation.get("artifact_path"):
            path = Path(installation["artifact_path"])
            return path if installation.get("artifact_kind") == "bundle" else path.parent
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

        model_ref = self.artifact_path() or self.model
        if model_ref is not None:
            model_ref = str(model_ref)
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
    # SAM2 keeps a large parameter graph and temporary feature maps in the
    # worker address space even for tiny inputs. Give the isolated worker a
    # realistic virtual-memory budget instead of the generic 4 GiB ceiling.
    memory_requirement_mb = 4096

    def __init__(self, model="sam2_s.pt"):
        super().__init__("sam", "vision.segment", model)

    def _check_dependency(self):
        if importlib.util.find_spec("ultralytics") is None:
            _missing("ultralytics")

    def _load_model(self):
        self._check_dependency()
        from ultralytics import SAM

        model_ref = self.artifact_path() or {"sam2-small": "sam2_s.pt"}.get(self.model, self.model)
        model_ref = str(model_ref)
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
        # PaddlePaddle 3.3.1 can select oneDNN by default on Linux. The
        # PP-OCRv5 PIR graph contains attributes that the bundled oneDNN
        # executor does not implement, so disable that optional engine for a
        # deterministic CPU path.
        os.environ["FLAGS_use_mkldnn"] = "0"
        from paddleocr import PaddleOCR

        root = self.artifact_root()
        kwargs = {}
        if root:
            # PaddleOCR 3.x otherwise defaults to PP-OCRv6 and downloads its
            # document-orientation/unwarping models. Pin the model names to
            # the checked-in PP-OCRv5 bundle and disable those extra stages so
            # an offline, verified install remains deterministic.
            det = root / "det"
            rec = root / "rec"
            if det.is_dir():
                kwargs["text_detection_model_name"] = "PP-OCRv5_mobile_det"
                kwargs["text_detection_model_dir"] = str(det)
            if rec.is_dir():
                kwargs["text_recognition_model_name"] = "PP-OCRv5_mobile_rec"
                kwargs["text_recognition_model_dir"] = str(rec)
            kwargs.update(
                {
                    "use_doc_orientation_classify": False,
                    "use_doc_unwarping": False,
                    "use_textline_orientation": False,
                }
            )
        if not kwargs and not self._allow_unverified_models:
            raise WorkerError("PaddleOCR bundle must contain det/ and rec/ model directories", code="unsupported_artifact", retryable=False)
        self._model = PaddleOCR(**kwargs)

    def infer(self, input_path, options, cache):
        self.load()
        raw = self._model.predict(str(input_path)) if hasattr(self._model, "predict") else self._model.ocr(str(input_path), cls=False)
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
        local = self.artifact_path()
        model_ref = str(local) if local else model_ref
        self._pipeline = pipeline("depth-estimation", model=model_ref, local_files_only=True)

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
        local = self.artifact_path()
        if local and Path(local).suffix == ".jit":
            import torch

            self._model = torch.jit.load(str(local), map_location="cpu")
        else:
            from silero_vad import load_silero_vad

            if not self._allow_unverified_models:
                raise WorkerError("verified Silero artifact must be a .jit file", code="unsupported_artifact", retryable=False)
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

    requires_provider_environment = True
    requires_local_model_directory = True

    def __init__(self, command="mineru", model="mineru-2"):
        super().__init__("mineru", "document.parse", model)
        self.command = command

    def _check_dependency(self):
        if shutil.which(self.command) is None:
            _missing(self.command)

    @staticmethod
    def _configured_model_dir():
        explicit = os.environ.get("SPECIALIST_MINERU_MODEL_DIR")
        if explicit:
            return Path(explicit).expanduser()
        config_path = Path(os.environ.get("MINERU_TOOLS_CONFIG_JSON", "~/mineru.json")).expanduser()
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            models_dir = config.get("models-dir") if isinstance(config, dict) else None
            pipeline = models_dir.get("pipeline") if isinstance(models_dir, dict) else None
            return Path(pipeline).expanduser() if isinstance(pipeline, str) and pipeline.strip() else None
        except (OSError, ValueError, TypeError):
            return None

    def doctor(self, hardware):
        details = super().doctor(hardware)
        if details.get("status") != "ready" or self._allow_unverified_models:
            return details
        model_dir = self._configured_model_dir()
        if not model_dir or not model_dir.is_dir() or not any(model_dir.iterdir()):
            return {
                **details,
                "status": "not ready",
                "error": {
                    "code": "model_directory_required",
                    "message": "MinerU pipeline models are not configured; set SPECIALIST_MINERU_MODEL_DIR or configure ~/mineru.json",
                },
            }
        return {**details, "model_directory": str(model_dir)}

    def infer(self, input_path, options, cache):
        self.load()
        self._check_dependency()
        output_dir = cache.results / f"document-{cache.input_hash(input_path)[:16]}"
        output_dir.mkdir(parents=True, exist_ok=True)
        environment = os.environ.copy()
        root = self.artifact_root()
        artifact = self.artifact_path()
        model_dir = self._configured_model_dir()
        if not self._allow_unverified_models and (not model_dir or not model_dir.is_dir() or not any(model_dir.iterdir())):
            raise WorkerError("MinerU pipeline models are not configured; set SPECIALIST_MINERU_MODEL_DIR or configure ~/mineru.json", code="model_directory_required", retryable=False)
        if model_dir:
            environment["SPECIALIST_MODEL_DIR"] = str(model_dir)
        if artifact:
            environment["SPECIALIST_MODEL_ARTIFACT"] = str(artifact)
        if not self._allow_unverified_models:
            # MinerU's CLI downloads pipeline/VLM weights on demand. A
            # verified Specialist artifact must be an offline boundary; an
            # operator can provision local models and set MINERU_MODEL_SOURCE
            # explicitly when using a controlled environment.
            environment["MINERU_MODEL_SOURCE"] = "local"
        try:
            completed = _run_external([self.command, "-p", str(input_path), "-o", str(output_dir)], timeout=float(options.get("timeout_seconds", 900)), env=environment)
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
        self.load()
        self._check_dependency()
        environment = os.environ.copy()
        root = self.artifact_root()
        artifact = self.artifact_path()
        if root:
            environment.setdefault("OMNIPARSER_MODEL_DIR", str(root))
            environment.setdefault("SPECIALIST_MODEL_DIR", str(root))
        if artifact:
            environment["SPECIALIST_MODEL_ARTIFACT"] = str(artifact)
        if not self._allow_unverified_models:
            # Prevent a wrapper from silently reaching Hugging Face/ModelScope
            # when the checked-in bundle is the declared source of truth.
            environment["HF_HUB_OFFLINE"] = "1"
            environment["TRANSFORMERS_OFFLINE"] = "1"
        try:
            completed = _run_external([self.command, str(input_path), "--json"], timeout=float(options.get("timeout_seconds", 120)), env=environment)
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
        self.load()
        self._check_dependency()
        try:
            with wave.open(str(input_path), "rb") as audio:
                if audio.getsampwidth() != 2 or audio.getnchannels() not in (1, 2):
                    raise WorkerError("whisper.cpp currently requires mono/stereo 16-bit PCM WAV", code="unsupported_audio_format", retryable=False)
        except (OSError, EOFError, wave.Error) as exc:
            raise WorkerError("whisper.cpp requires a valid PCM WAV input", code="unsupported_audio_format", retryable=False) from exc
        model_path = self.artifact_path() or self.model
        model_path = str(model_path)
        # Remove stale sidecar output so a failed invocation cannot be
        # mistaken for a successful result from an earlier request.
        candidates = [Path(str(input_path) + ".json"), input_path.with_suffix(".json")]
        for candidate in candidates:
            candidate.unlink(missing_ok=True)
        command = [self.binary, "-m", model_path, "-f", str(input_path), "--output-json", "--no-prints"]
        try:
            completed = _run_external(command, timeout=float(options.get("timeout_seconds", 300)))
        except subprocess.TimeoutExpired as exc:
            raise WorkerError("whisper.cpp timed out", code="provider_timeout") from exc
        if completed.returncode:
            raise WorkerError(completed.stderr.strip()[-2000:] or "whisper.cpp failed", code="provider_error", retryable=True)
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

        def timestamp(value):
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
            if isinstance(value, str):
                value = value.strip().replace(",", ".")
                try:
                    parts = value.split(":")
                    if len(parts) == 3:
                        hours, minutes, seconds = parts
                        return float(hours) * 3600 + float(minutes) * 60 + float(seconds)
                    return float(value)
                except ValueError:
                    return None
            return None

        raw_segments = parsed.get("segments") or parsed.get("transcription") or []
        segments = []
        for item in raw_segments:
            if not isinstance(item, dict):
                continue
            timestamps = item.get("timestamps") or {}
            start = timestamp(item.get("start", timestamps.get("from")))
            end = timestamp(item.get("end", timestamps.get("to")))
            if start is None or end is None or end < start:
                continue
            segments.append({"start": start, "end": end, "text": str(item.get("text", "")).strip()})
        text = parsed.get("text") or " ".join(item["text"] for item in segments if item["text"]).strip()
        return {"text": str(text), "segments": segments}, []

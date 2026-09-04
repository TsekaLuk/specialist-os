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
            requires_artifact = bool(getattr(self, "requires_verified_artifact", True))
            if requires_artifact and not self._allow_unverified_models and not (installation and installation.get("artifact_path") and installation.get("sha256")):
                raise WorkerError("a verified model artifact is required; install with --source and --sha256 or explicitly allow provider downloads", code="model_artifact_required", retryable=False)
            if requires_artifact and installation and installation.get("artifact_path") and not self._allow_unverified_models:
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


def _paddleocr_kwargs(root: Path | None) -> dict:
    kwargs = {}
    if root:
        # PaddleOCR 3.x otherwise defaults to PP-OCRv6 and downloads its
        # document-orientation/unwarping models. Keep all inference assets
        # inside the verified bundle used by the provider worker.
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
                "enable_mkldnn": False,
            }
        )
    return kwargs


def _paddleocr_blocks(raw) -> list[dict]:
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
    return blocks


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
        kwargs = _paddleocr_kwargs(root)
        if not kwargs and not self._allow_unverified_models:
            raise WorkerError("PaddleOCR bundle must contain det/ and rec/ model directories", code="unsupported_artifact", retryable=False)
        self._model = PaddleOCR(**kwargs)

    def infer(self, input_path, options, cache):
        self.load()
        raw = self._model.predict(str(input_path)) if hasattr(self._model, "predict") else self._model.ocr(str(input_path), cls=False)
        return {"blocks": _paddleocr_blocks(raw)}, []


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
        mode = str(options.get("mode", "relative")).lower()
        if mode not in {"relative", "metric"}:
            raise WorkerError("mode must be relative or metric", code="invalid_options", retryable=False)
        if mode == "metric":
            raise WorkerError("Depth Anything returns relative depth; a metric calibration provider is required", code="unsupported_mode", retryable=False)
        self.load()
        from PIL import Image

        output = self._pipeline(Image.open(input_path))
        preview = cache.results / f"{cache.input_hash(input_path)[:16]}-depth.png"
        cache.ensure_dirs()
        output["depth"].save(preview)
        width, height = output["depth"].size
        return {"width": width, "height": height, "depth_map": None, "preview": str(preview), "mode": "relative", "unit": None, "estimated": False}, []


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

    @staticmethod
    def _structure(output_dir):
        """Normalize MinerU's stable content-list export into our wire contract."""
        candidates = sorted(output_dir.rglob("*_content_list.json"))
        if not candidates:
            return None, [], [], []
        try:
            content = json.loads(candidates[0].read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None, [], [], []
        if not isinstance(content, list):
            return None, [], [], []

        tables, figures, formulas = [], [], []
        page_indexes = []
        for item in content:
            if not isinstance(item, dict):
                continue
            page_index = item.get("page_idx")
            if isinstance(page_index, int) and page_index >= 0:
                page_indexes.append(page_index)
            common = {"page": page_index, "bbox": item.get("bbox")}
            item_type = item.get("type")
            if item_type == "table":
                tables.append(
                    {
                        **common,
                        "html": str(item.get("table_body") or ""),
                        "caption": item.get("table_caption") or [],
                        "footnote": item.get("table_footnote") or [],
                        "image": item.get("img_path"),
                    }
                )
            elif item_type == "image":
                figures.append(
                    {
                        **common,
                        "caption": item.get("image_caption") or [],
                        "footnote": item.get("image_footnote") or [],
                        "image": item.get("img_path"),
                    }
                )
            elif item_type == "equation":
                formulas.append(
                    {
                        **common,
                        "text": str(item.get("text") or ""),
                        "format": str(item.get("text_format") or "latex"),
                        "image": item.get("img_path"),
                    }
                )
        pages = max(page_indexes) + 1 if page_indexes else None
        return pages, tables, figures, formulas

    def infer(self, input_path, options, cache):
        self.load()
        self._check_dependency()
        output_dir = cache.results / f"document-{cache.input_hash(input_path)[:16]}"
        if output_dir.exists():
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        environment = os.environ.copy()
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
        backend = str(options.get("backend", "pipeline"))
        allowed_backends = {"pipeline", "vlm-engine", "hybrid-engine", "vlm-http-client", "hybrid-http-client"}
        if backend not in allowed_backends:
            raise WorkerError(f"backend must be one of {sorted(allowed_backends)}", code="invalid_options", retryable=False)
        method = str(options.get("method", "auto"))
        if method not in {"auto", "txt", "ocr"}:
            raise WorkerError("method must be auto, txt, or ocr", code="invalid_options", retryable=False)
        command = [self.command, "-p", str(input_path), "-o", str(output_dir), "--backend", backend, "--method", method]
        for option, flag in (("start", "--start"), ("end", "--end")):
            value = options.get(option)
            if value is not None:
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise WorkerError(f"{option} must be a non-negative integer", code="invalid_options", retryable=False)
                command.extend([flag, str(value)])
        if options.get("start") is not None and options.get("end") is not None and options["end"] < options["start"]:
            raise WorkerError("end must be greater than or equal to start", code="invalid_options", retryable=False)
        language = options.get("language")
        allowed_languages = {"ch", "ch_server", "korean", "ta", "te", "ka", "th", "el", "arabic", "east_slavic", "cyrillic", "devanagari"}
        if language is not None:
            if language not in allowed_languages:
                raise WorkerError(f"language must be one of {sorted(allowed_languages)}", code="invalid_options", retryable=False)
            command.extend(["--lang", language])
        for option, flag in (("formula", "--formula"), ("table", "--table"), ("image_analysis", "--image-analysis")):
            value = options.get(option)
            if value is not None:
                if not isinstance(value, bool):
                    raise WorkerError(f"{option} must be boolean", code="invalid_options", retryable=False)
                command.extend([flag, "true" if value else "false"])
        if backend in {"vlm-http-client", "hybrid-http-client"}:
            server_url = options.get("server_url")
            if not isinstance(server_url, str) or not server_url.startswith(("http://", "https://")):
                raise WorkerError("remote MinerU backends require an http(s) server_url", code="invalid_options", retryable=False)
            if not options.get("allow_remote"):
                raise WorkerError("remote MinerU backends require allow_remote=true", code="remote_not_allowed", retryable=False)
            command.extend(["--url", server_url])
        else:
            # MinerU 3.4 starts a loopback API even for local inference. HTTPX
            # initializes configured proxy transports before evaluating
            # NO_PROXY, so remove proxy variables only for this local child.
            for key in ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
                environment.pop(key, None)
        try:
            completed = _run_external(command, timeout=float(options.get("timeout_seconds", 900)), env=environment)
        except subprocess.TimeoutExpired as exc:
            raise WorkerError("document parser timed out", code="provider_timeout") from exc
        if completed.returncode:
            raise WorkerError(completed.stderr.strip()[-2000:] or "document parser failed", code="provider_error", retryable=True)
        markdown_files = sorted(output_dir.rglob("*.md"))
        markdown = markdown_files[0].read_text(encoding="utf-8") if markdown_files else completed.stdout.strip()
        pages, tables, figures, formulas = self._structure(output_dir)
        output_files = [str(path) for path in sorted(output_dir.rglob("*")) if path.is_file() and not path.is_symlink()]
        return {
            "markdown": markdown,
            "pages": pages,
            "tables": tables,
            "figures": figures,
            "formulas": formulas,
            "files": output_files,
            "artifacts_path": str(output_dir),
        }, []


class OmniParserProvider(OptionalProvider):
    """Local OmniParser v2 pipeline using the verified upstream weights."""

    memory_requirement_mb = 6144
    disk_requirement_mb = 2500

    def __init__(self, model="omniparser-v2"):
        super().__init__("omniparser", "screen.parse", model)

    def _check_dependency(self):
        for module, package in (
            ("ultralytics", "ultralytics"),
            ("transformers", "transformers"),
            ("torch", "torch"),
            ("torchvision", "torchvision"),
            ("paddleocr", "paddleocr"),
            ("paddle", "paddlepaddle"),
            ("PIL", "Pillow"),
        ):
            if importlib.util.find_spec(module) is None:
                _missing(package)

    def _load_model(self):
        self._check_dependency()
        root = self.artifact_root()
        if root is None:
            raise WorkerError("OmniParser requires a verified model bundle", code="model_artifact_required", retryable=False)
        detector_path = root / "icon_detect" / "model.pt"
        caption_path = root / "icon_caption"
        processor_path = root / "processor"
        ocr_path = root / "ocr"
        required = (
            detector_path,
            caption_path / "model.safetensors",
            caption_path / "configuration_florence2.py",
            caption_path / "modeling_florence2.py",
            processor_path / "tokenizer.json",
            processor_path / "processing_florence2.py",
            ocr_path / "det",
            ocr_path / "rec",
        )
        if any(not path.exists() for path in required):
            raise WorkerError("OmniParser bundle is incomplete", code="unsupported_artifact", retryable=False)

        os.environ["FLAGS_use_mkldnn"] = "0"
        import torch
        from paddleocr import PaddleOCR
        from transformers import BartTokenizerFast, CLIPImageProcessor
        from transformers.dynamic_module_utils import get_class_from_dynamic_module
        from ultralytics import YOLO

        try:
            self._detector = YOLO(str(detector_path))
            processor_class = get_class_from_dynamic_module(
                "processing_florence2.Florence2Processor",
                str(processor_path),
                local_files_only=True,
            )
            self._processor = processor_class(
                image_processor=CLIPImageProcessor.from_pretrained(str(processor_path), local_files_only=True),
                tokenizer=BartTokenizerFast.from_pretrained(str(processor_path), local_files_only=True),
            )
            config_class = get_class_from_dynamic_module(
                "configuration_florence2.Florence2Config",
                str(caption_path),
                local_files_only=True,
            )
            model_class = get_class_from_dynamic_module(
                "modeling_florence2.Florence2ForConditionalGeneration",
                str(caption_path),
                local_files_only=True,
            )
            caption_config = config_class.from_pretrained(str(caption_path), local_files_only=True)
            self._caption_model = model_class.from_pretrained(
                str(caption_path),
                config=caption_config,
                local_files_only=True,
                torch_dtype=torch.float32,
            )
            self._caption_model.eval()
            self._ocr = PaddleOCR(**_paddleocr_kwargs(ocr_path))
        except Exception as exc:
            raise WorkerError(f"could not load OmniParser pipeline: {exc}", code="model_not_configured", retryable=False) from exc
        self._device = "cpu"

    @staticmethod
    def _area(box):
        return max(0.0, float(box[2]) - float(box[0])) * max(0.0, float(box[3]) - float(box[1]))

    @classmethod
    def _overlap_ratio(cls, left, right):
        intersection = max(0.0, min(float(left[2]), float(right[2])) - max(float(left[0]), float(right[0]))) * max(
            0.0, min(float(left[3]), float(right[3])) - max(float(left[1]), float(right[1]))
        )
        left_area = cls._area(left)
        return intersection / left_area if left_area > 0 else 0.0

    @classmethod
    def _intersection_score(cls, left, right):
        intersection = max(0.0, min(float(left[2]), float(right[2])) - max(float(left[0]), float(right[0]))) * max(
            0.0, min(float(left[3]), float(right[3])) - max(float(left[1]), float(right[1]))
        )
        left_area, right_area = cls._area(left), cls._area(right)
        union = left_area + right_area - intersection
        values = [intersection / union if union > 0 else 0.0]
        if left_area > 0:
            values.append(intersection / left_area)
        if right_area > 0:
            values.append(intersection / right_area)
        return max(values)

    @classmethod
    def _merge_elements(cls, ocr_elements, icon_elements, iou_threshold):
        icons = []
        for index, candidate in enumerate(icon_elements):
            if any(
                index != other_index
                and cls._area(candidate["bbox"]) > cls._area(other["bbox"])
                and cls._intersection_score(candidate["bbox"], other["bbox"]) > iou_threshold
                for other_index, other in enumerate(icon_elements)
            ):
                continue
            icons.append(dict(candidate))

        remaining_ocr = [dict(item) for item in ocr_elements]
        merged = []
        for icon in icons:
            labels = []
            kept_ocr = []
            icon_inside_text = False
            for text in remaining_ocr:
                if cls._overlap_ratio(text["bbox"], icon["bbox"]) > 0.8:
                    labels.append(str(text.get("content") or ""))
                elif cls._overlap_ratio(icon["bbox"], text["bbox"]) > 0.8:
                    icon_inside_text = True
                    kept_ocr.append(text)
                else:
                    kept_ocr.append(text)
            if icon_inside_text and not labels:
                continue
            remaining_ocr = kept_ocr
            if labels:
                icon["content"] = " ".join(value for value in labels if value).strip() or None
            merged.append(icon)
        return remaining_ocr + merged

    def _select_device(self, requested, torch):
        device = str(requested or "cpu").lower()
        if device == "cuda" and not torch.cuda.is_available():
            raise WorkerError("CUDA is not available for OmniParser", code="unsupported_device", retryable=False)
        mps_backend = getattr(torch.backends, "mps", None)
        if device == "mps" and (mps_backend is None or not mps_backend.is_available()):
            raise WorkerError("MPS is not available for OmniParser", code="unsupported_device", retryable=False)
        if device not in {"cpu", "mps", "cuda"}:
            raise WorkerError("device must be cpu, mps, or cuda", code="invalid_options", retryable=False)
        if self._device != device:
            dtype = torch.float32 if device == "cpu" else torch.float16
            self._caption_model.to(device=device, dtype=dtype)
            self._device = device
        return device

    @staticmethod
    def _number_option(options, name, default, minimum, maximum, integer=False):
        value = options.get(name, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise WorkerError(f"{name} must be numeric", code="invalid_options", retryable=False)
        if integer and not isinstance(value, int):
            raise WorkerError(f"{name} must be an integer", code="invalid_options", retryable=False)
        if not minimum <= value <= maximum:
            raise WorkerError(f"{name} must be between {minimum} and {maximum}", code="invalid_options", retryable=False)
        return int(value) if integer else float(value)

    def infer(self, input_path, options, cache):
        threshold = self._number_option(options, "box_threshold", 0.05, 0.001, 1.0)
        iou_threshold = self._number_option(options, "iou_threshold", 0.7, 0.0, 1.0)
        max_elements = self._number_option(options, "max_elements", 300, 1, 1000, integer=True)
        caption_batch_size = self._number_option(options, "caption_batch_size", 32, 1, 128, integer=True)
        requested_device = str(options.get("device") or "cpu").lower()
        if requested_device not in {"cpu", "mps", "cuda"}:
            raise WorkerError("device must be cpu, mps, or cuda", code="invalid_options", retryable=False)

        self.load()
        import torch
        from PIL import Image, ImageDraw

        device = self._select_device(requested_device, torch)

        try:
            with Image.open(input_path) as source:
                image = source.convert("RGB")
            width, height = image.size
            raw_ocr = self._ocr.predict(str(input_path)) if hasattr(self._ocr, "predict") else self._ocr.ocr(str(input_path), cls=False)
            ocr_blocks = _paddleocr_blocks(raw_ocr)
            ocr_elements = []
            for block in ocr_blocks:
                box = block.get("bbox") or []
                if len(box) != 4 or width <= 0 or height <= 0:
                    continue
                normalized = [float(box[0]) / width, float(box[1]) / height, float(box[2]) / width, float(box[3]) / height]
                if self._area(normalized) <= 0:
                    continue
                ocr_elements.append(
                    {
                        "type": "text",
                        "bbox": normalized,
                        "interactivity": False,
                        "content": str(block.get("text") or ""),
                        "confidence": block.get("confidence"),
                        "source": "paddleocr",
                    }
                )

            detection = self._detector.predict(
                source=image,
                conf=threshold,
                iou=iou_threshold,
                max_det=max_elements,
                device=device,
                verbose=False,
            )[0]
            boxes = getattr(detection, "boxes", None)
            icon_elements = []
            if boxes is not None:
                coordinates = boxes.xyxy.detach().cpu().tolist()
                scores = boxes.conf.detach().cpu().tolist()
                for index, box in enumerate(coordinates):
                    normalized = [float(box[0]) / width, float(box[1]) / height, float(box[2]) / width, float(box[3]) / height]
                    if self._area(normalized) <= 0:
                        continue
                    icon_elements.append(
                        {
                            "type": "icon",
                            "bbox": normalized,
                            "interactivity": True,
                            "content": None,
                            "confidence": float(scores[index]) if index < len(scores) else None,
                            "source": "omniparser_icon_detector",
                        }
                    )
            elements = self._merge_elements(ocr_elements, icon_elements, iou_threshold)[:max_elements]

            caption_indices = []
            crops = []
            for index, element in enumerate(elements):
                if element.get("type") != "icon" or element.get("content"):
                    continue
                box = element["bbox"]
                left, top = max(0, int(box[0] * width)), max(0, int(box[1] * height))
                right, bottom = min(width, int(box[2] * width)), min(height, int(box[3] * height))
                if right <= left or bottom <= top:
                    continue
                crops.append(image.crop((left, top, right, bottom)).resize((64, 64), Image.Resampling.BICUBIC))
                caption_indices.append(index)

            captions = []
            dtype = torch.float32 if device == "cpu" else torch.float16
            for offset in range(0, len(crops), caption_batch_size):
                batch = crops[offset : offset + caption_batch_size]
                inputs = self._processor(images=batch, text=["<CAPTION>"] * len(batch), return_tensors="pt", do_resize=False)
                inputs = {key: value.to(device=device, dtype=dtype) if getattr(value, "is_floating_point", lambda: False)() else value.to(device) for key, value in inputs.items()}
                with torch.inference_mode():
                    generated = self._caption_model.generate(
                        input_ids=inputs["input_ids"],
                        pixel_values=inputs["pixel_values"],
                        max_new_tokens=20,
                        num_beams=1,
                        do_sample=False,
                    )
                captions.extend(text.strip() for text in self._processor.batch_decode(generated, skip_special_tokens=True))
            for index, caption in zip(caption_indices, captions):
                elements[index]["content"] = caption

            preview = image.copy()
            draw = ImageDraw.Draw(preview)
            palette = ("#ef5b5b", "#169c91", "#287bc1", "#b35aa5", "#ef8b2c")
            for index, element in enumerate(elements):
                box = element["bbox"]
                pixel_box = [round(box[0] * width), round(box[1] * height), round(box[2] * width), round(box[3] * height)]
                color = palette[index % len(palette)]
                draw.rectangle(pixel_box, outline=color, width=max(2, width // 600))
                label = str(index)
                label_box = draw.textbbox((pixel_box[0], pixel_box[1]), label)
                draw.rectangle((label_box[0] - 2, label_box[1] - 2, label_box[2] + 2, label_box[3] + 2), fill=color)
                draw.text((pixel_box[0], pixel_box[1]), label, fill="white")
                element["id"] = f"element_{index}"
                element["bbox"] = [round(value, 6) for value in box]
            cache.ensure_dirs()
            preview_path = cache.results / f"omniparser-{cache.input_hash(input_path)[:16]}.png"
            preview.save(preview_path, format="PNG")
        except WorkerError:
            raise
        except Exception as exc:
            raise WorkerError(f"OmniParser inference failed: {exc}", code="provider_error", retryable=False) from exc
        return {"elements": elements, "image": {"width": width, "height": height}, "preview": str(preview_path)}, []


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

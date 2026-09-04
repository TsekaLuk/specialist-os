"""Lazy adapters for the optional model providers in ADR-PRD-002."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
from pathlib import Path

from ..artifacts import ArtifactError, ArtifactStore
from .expansion import _cosine
from .ipc import WorkerError
from .optional import OptionalProvider, _missing


class ExpansionOptionalProvider(OptionalProvider):
    # These providers use operator-managed/server-managed model assets. The
    # package environment is still isolated, while model downloads remain
    # under each upstream provider's documented configuration.
    requires_verified_artifact = False

    def _missing_dependency(self, package: str):
        try:
            available = importlib.util.find_spec(package) is not None
        except (ImportError, ModuleNotFoundError, ValueError):
            available = False
        if not available:
            _missing(package)


class MediaPipeProvider(ExpansionOptionalProvider):
    def __init__(self, capability: str):
        super().__init__("mediapipe", capability, "mediapipe-tasks")

    def _check_dependency(self):
        self._missing_dependency("mediapipe")

    def _load_model(self):
        self._check_dependency()
        self._mp = importlib.import_module("mediapipe")
        self._solution = getattr(self._mp, "solutions", None)
        if self._solution is None:
            raise WorkerError("MediaPipe Tasks model assets must be configured for this provider", code="model_not_configured", retryable=False)

    def infer(self, input_path, options, cache):
        self.load()
        # The legacy solutions API is available in some MediaPipe releases;
        # Tasks installations can provide a custom task asset path through the
        # same isolated provider without changing the result contract.
        try:
            from PIL import Image
        except ImportError as exc:
            raise WorkerError("Pillow is required by the MediaPipe image adapter", code="dependency_missing", retryable=False) from exc
        image = Image.open(input_path).convert("RGB")
        rgb = __import__("numpy").asarray(image)
        if self.capability == "human.pose" and getattr(self._solution, "pose", None):
            with self._solution.pose.Pose(static_image_mode=True, model_complexity=1) as model:
                raw = model.process(rgb)
            persons = []
            if raw.pose_landmarks:
                persons.append({"id": "person_0", "landmarks": [_landmark(item, index) for index, item in enumerate(raw.pose_landmarks.landmark)]})
            return {"persons": persons}, []
        if self.capability == "human.hand_landmarks" and getattr(self._solution, "hands", None):
            with self._solution.hands.Hands(static_image_mode=True, max_num_hands=2) as model:
                raw = model.process(rgb)
            hands = []
            for index, landmarks in enumerate(raw.multi_hand_landmarks or []):
                handedness = (raw.multi_handedness[index].classification[0].label.lower() if index < len(raw.multi_handedness or []) else "unknown")
                hands.append({"hand": handedness if handedness in {"left", "right"} else "unknown", "landmarks": [_landmark(item, number) for number, item in enumerate(landmarks.landmark)]})
            return {"hands": hands}, []
        if self.capability == "human.gesture" and getattr(self._solution, "hands", None):
            with self._solution.hands.Hands(static_image_mode=True, max_num_hands=2) as model:
                raw = model.process(rgb)
            gestures = []
            for landmarks in raw.multi_hand_landmarks or []:
                points = landmarks.landmark
                # A small, deterministic open/closed hand classifier based on
                # fingertip-to-PIP ordering. The landmark model remains the
                # source of truth; this only names the observed pose.
                extended = sum(points[tip].y < points[pip].y for tip, pip in ((8, 6), (12, 10), (16, 14), (20, 18)) if len(points) > tip)
                label = "open_hand" if extended >= 3 else "closed_hand"
                gestures.append({"gesture": label, "confidence": None})
            if not gestures:
                gestures.append({"gesture": None, "confidence": None})
            return {"gesture": gestures[0]["gesture"], "confidence": gestures[0]["confidence"], "gestures": gestures}, []
        if self.capability == "human.face_landmarks" and getattr(self._solution, "face_mesh", None):
            with self._solution.face_mesh.FaceMesh(static_image_mode=True, max_num_faces=10) as model:
                raw = model.process(rgb)
            faces = [{"id": f"face_{index}", "landmarks": [_landmark(item, number) for number, item in enumerate(mesh.landmark)]} for index, mesh in enumerate(raw.multi_face_landmarks or [])]
            return {"faces": faces}, []
        raise WorkerError("MediaPipe model does not expose this capability in the installed distribution", code="unsupported_provider_api", retryable=False)


def _landmark(value, index):
    return {"name": str(index), "x": float(value.x), "y": float(value.y), "z": float(getattr(value, "z", 0.0)), "visibility": float(getattr(value, "visibility", 1.0))}


class PyannoteProvider(ExpansionOptionalProvider):
    DEFAULT_MODEL = "pyannote-community/speaker-diarization-community-1"
    DEFAULT_REVISION = "8a527374977391da736e0daaef26855d949d9685"

    def __init__(self):
        super().__init__("pyannote", "speech.diarize", "pyannote-community-1")

    def _check_dependency(self):
        self._missing_dependency("pyannote.audio")
        self._missing_dependency("torch")
        self._missing_dependency("soundfile")

    def _load_model(self):
        self._check_dependency()
        from pyannote.audio import Pipeline

        model_name = os.environ.get("SPECIALIST_PYANNOTE_MODEL", self.DEFAULT_MODEL)
        revision = os.environ.get("SPECIALIST_PYANNOTE_REVISION", self.DEFAULT_REVISION)
        token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_HUB_TOKEN")
        kwargs = {"revision": revision}
        if token:
            kwargs["token"] = token
        try:
            self._pipeline = Pipeline.from_pretrained(model_name, **kwargs)
        except Exception as exc:
            raise WorkerError(f"could not load pyannote pipeline: {exc}", code="model_not_configured", retryable=False) from exc

    @staticmethod
    def _normalize_segments(output, exclusive=False):
        diarization = getattr(output, "exclusive_speaker_diarization", None) if exclusive else None
        if diarization is None:
            diarization = getattr(output, "speaker_diarization", None)
        if diarization is None:
            diarization = output
        if hasattr(diarization, "itertracks"):
            tracks = ((turn, speaker) for turn, _, speaker in diarization.itertracks(yield_label=True))
        else:
            tracks = iter(diarization)
        segments = [
            {"speaker": str(speaker), "start": float(turn.start), "end": float(turn.end), "confidence": None}
            for turn, speaker in tracks
        ]
        segments.sort(key=lambda item: (item["start"], item["end"], item["speaker"]))
        return segments

    def infer(self, input_path, options, cache):
        requested_device = str(options.get("device", "cpu")).lower()
        if requested_device not in {"cpu", "mps", "cuda"}:
            raise WorkerError("device must be cpu, mps, or cuda", code="invalid_options", retryable=False)
        exclusive = options.get("exclusive", False)
        if not isinstance(exclusive, bool):
            raise WorkerError("exclusive must be boolean", code="invalid_options", retryable=False)
        inference_options = {}
        for key in ("num_speakers", "min_speakers", "max_speakers"):
            value = options.get(key)
            if value is not None:
                if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                    raise WorkerError(f"{key} must be a positive integer", code="invalid_options", retryable=False)
                inference_options[key] = value
        if inference_options.get("min_speakers", 0) > inference_options.get("max_speakers", float("inf")):
            raise WorkerError("min_speakers must be less than or equal to max_speakers", code="invalid_options", retryable=False)

        self.load()
        import torch

        if requested_device == "cuda" and not torch.cuda.is_available():
            raise WorkerError("CUDA is not available for the pyannote provider", code="unsupported_device", retryable=False)
        mps_backend = getattr(torch.backends, "mps", None)
        if requested_device == "mps" and (mps_backend is None or not mps_backend.is_available()):
            raise WorkerError("MPS is not available for the pyannote provider", code="unsupported_device", retryable=False)
        if getattr(self, "_device", None) != requested_device:
            self._pipeline.to(torch.device(requested_device))
            self._device = requested_device
        try:
            import soundfile

            samples, sample_rate = soundfile.read(str(input_path), dtype="float32", always_2d=True)
            waveform = torch.from_numpy(samples.T.copy())
            if waveform.shape[0] > 1:
                waveform = waveform.mean(dim=0, keepdim=True)
            output = self._pipeline({"waveform": waveform, "sample_rate": int(sample_rate)}, **inference_options)
        except Exception as exc:
            raise WorkerError(f"pyannote diarization failed: {exc}", code="provider_error", retryable=False) from exc

        segments = self._normalize_segments(output, exclusive)
        return {"segments": segments, "speakers": len({item["speaker"] for item in segments}), "exclusive": exclusive}, []


class DeepFilterNetProvider(ExpansionOptionalProvider):
    def __init__(self):
        super().__init__("deepfilternet", "audio.denoise", "deepfilternet-2")

    def _check_dependency(self):
        self._missing_dependency("df")

    def _load_model(self):
        self._check_dependency()
        try:
            self._enhance = importlib.import_module("df.enhance")
        except ImportError as exc:
            raise WorkerError("DeepFilterNet enhance API is unavailable", code="unsupported_provider_api", retryable=False) from exc

    def infer(self, input_path, options, cache):
        self.load()
        profile = str(options.get("strength", options.get("profile", "balanced"))).lower()
        if profile not in {"light", "balanced", "strong"}:
            raise WorkerError("strength must be light, balanced, or strong", code="invalid_options", retryable=False)
        output = cache.results / f"denoised-{cache.input_hash(input_path)[:16]}-{profile}.wav"
        try:
            if hasattr(self._enhance, "enhance_file"):
                self._enhance.enhance_file(str(input_path), str(output))
            else:
                # DeepFilterNet 0.5 exposes the tensor-level API. Keep the
                # provider boundary responsible for loading, enhancement and
                # persistence so callers still receive one audio artifact.
                import torch
                from df.enhance import enhance, init_df
                from df.io import load_audio, resample, save_audio

                model_name = {"light": "DeepFilterNet", "balanced": "DeepFilterNet2", "strong": "DeepFilterNet3"}[profile]
                model, df_state, _suffix = init_df(model_name, log_file=None, log_level="ERROR")
                model_rate = df_state.sr() if callable(getattr(df_state, "sr", None)) else df_state.sr
                audio, metadata = load_audio(str(input_path), sr=model_rate, verbose=False)
                with torch.no_grad():
                    enhanced = enhance(model, df_state, audio, pad=True)
                if metadata.sample_rate != model_rate:
                    enhanced = resample(enhanced.to("cpu"), model_rate, metadata.sample_rate)
                save_audio(str(output), enhanced.to("cpu"), sr=metadata.sample_rate, log=False)
        except WorkerError:
            raise
        except Exception as exc:
            raise WorkerError(f"DeepFilterNet failed: {exc}", code="provider_error", retryable=False) from exc
        import wave

        with wave.open(str(output), "rb") as stream:
            duration_ms = stream.getnframes() / float(stream.getframerate() or 1) * 1000
            sample_rate, channels = stream.getframerate(), stream.getnchannels()
        return {"audio": {"path": str(output), "mime": "audio/wav", "duration_ms": duration_ms, "sample_rate": sample_rate, "channels": channels, "profile": profile, "processed": True}, "source_preserved": True, "profile": profile}, []


class OpenCLIPProvider(ExpansionOptionalProvider):
    def __init__(self, capability: str):
        super().__init__("openclip", capability, "siglip2-balanced")

    def _check_dependency(self):
        self._missing_dependency("open_clip")
        self._missing_dependency("torch")
        self._missing_dependency("PIL")

    def _load_model(self):
        self._check_dependency()
        import open_clip

        profiles = {
            "siglip2-balanced": ("ViT-B-32-SigLIP2-256", "webli"),
            "mobileclip2-fast": ("MobileCLIP2-S0", "dfndr2b"),
        }
        model_name, pretrained = profiles.get(self.model, profiles["siglip2-balanced"])
        model_name = os.environ.get("SPECIALIST_OPENCLIP_MODEL", model_name)
        pretrained = os.environ.get("SPECIALIST_OPENCLIP_PRETRAINED", pretrained)
        try:
            self._model, _, self._preprocess = open_clip.create_model_and_transforms(model_name, pretrained=pretrained)
            self._tokenizer = open_clip.get_tokenizer(model_name)
            self._model.eval()
            self._device = "cpu"
        except Exception as exc:
            raise WorkerError(f"could not load OpenCLIP model: {exc}", code="model_not_configured", retryable=False) from exc

    def infer(self, input_path, options, cache):
        self.load()
        import torch
        from PIL import Image

        device = self._select_device(options, torch)
        text = options.get("text")
        if self.capability in {"vision.embed", "vision.embed_text"}:
            if self.capability == "vision.embed_text":
                if not isinstance(text, str) or not text.strip():
                    raise WorkerError("vision.embed_text requires a non-empty text option", code="invalid_options", retryable=False)
                values = self._text_embedding(text, torch, device)
            else:
                values = self._image_embedding(Path(input_path), torch, Image, device)
            path = _write_embedding(cache, values, self.model, prefix="embedding")
            dimension = len(values)
            return {"embedding": {"path": str(path), "dimension": dimension, "normalized": True, "model": self.model}, "embedding_path": str(path), "dimension": dimension, "normalized": True}, []
        if self.capability == "vision.similarity":
            other = options.get("other_input")
            if other is not None and text is not None:
                raise WorkerError("vision.similarity accepts either other_input or text, not both", code="invalid_options", retryable=False)
            query_values = self._image_embedding(Path(input_path), torch, Image, device)
            if isinstance(other, str):
                other_path = _resolve_file(other, cache, "other_input")
                candidate_values = self._image_embedding(other_path, torch, Image, device)
            elif isinstance(text, str) and text.strip():
                candidate_values = self._text_embedding(text, torch, device)
            else:
                raise WorkerError("vision.similarity requires other_input or a non-empty text option", code="invalid_options", retryable=False)
            return {"score": _cosine(query_values, candidate_values), "metric": "cosine", "model": self.model}, []
        if self.capability == "vision.search":
            corpus = options.get("corpus")
            if not isinstance(corpus, list) or not corpus:
                raise WorkerError("vision.search requires a non-empty corpus array", code="invalid_options", retryable=False)
            if len(corpus) > 10_000:
                raise WorkerError("vision.search corpus cannot contain more than 10000 items", code="invalid_options", retryable=False)
            query = options.get("query")
            if query is not None and (not isinstance(query, str) or not query.strip()):
                raise WorkerError("query must be a non-empty string when supplied", code="invalid_options", retryable=False)
            query_values = self._text_embedding(query, torch, device) if isinstance(query, str) else self._image_embedding(Path(input_path), torch, Image, device)
            rows = []
            warnings = []
            for index, item in enumerate(corpus):
                reference, metadata = _corpus_reference(item)
                try:
                    candidate_path = _resolve_file(reference, cache, f"corpus[{index}]")
                    candidate_values = self._image_embedding(candidate_path, torch, Image, device)
                except WorkerError as exc:
                    warnings.append(f"Skipped corpus[{index}]: {exc}")
                    continue
                row = {"reference": reference, "score": _cosine(query_values, candidate_values), "metric": "cosine", "model": self.model}
                if isinstance(metadata.get("id"), str) and metadata["id"]:
                    row["id"] = metadata["id"]
                if reference.startswith("artifact://"):
                    row["artifact"] = reference
                rows.append(row)
            if not rows:
                raise WorkerError("vision.search corpus contains no readable image files", code="invalid_input", retryable=False)
            rows.sort(key=lambda item: (-item["score"], str(item.get("reference", ""))))
            top_k = options.get("top_k", 20)
            if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 100:
                raise WorkerError("top_k must be an integer between 1 and 100", code="invalid_options", retryable=False)
            return {"results": rows[:top_k], "top_k": top_k, "metric": "cosine", "model": self.model}, warnings
        raise WorkerError(f"OpenCLIP does not support {self.capability}", code="unsupported_operation", retryable=False)

    def _select_device(self, options, torch):
        requested = str(options.get("device", "cpu")).lower()
        if requested == "cuda" and not torch.cuda.is_available():
            raise WorkerError("CUDA is not available for the OpenCLIP provider", code="unsupported_device", retryable=False)
        mps_backend = getattr(torch.backends, "mps", None)
        if requested == "mps" and (mps_backend is None or not mps_backend.is_available()):
            raise WorkerError("MPS is not available for the OpenCLIP provider", code="unsupported_device", retryable=False)
        if requested not in {"cpu", "mps", "cuda"}:
            raise WorkerError("device must be cpu, mps, or cuda", code="invalid_options", retryable=False)
        if getattr(self, "_device", "cpu") != requested:
            try:
                self._model.to(requested)
            except Exception as exc:
                raise WorkerError(f"could not move OpenCLIP model to {requested}: {exc}", code="unsupported_device", retryable=False) from exc
            self._device = requested
        return requested

    def _image_embedding(self, path: Path, torch, Image, device):
        with Image.open(path) as image:
            tensor = self._preprocess(image.convert("RGB")).unsqueeze(0).to(device)
        with torch.no_grad():
            vector = self._model.encode_image(tensor)
            vector = vector / vector.norm(dim=-1, keepdim=True).clamp_min(1e-12)
        return [float(item) for item in vector[0].detach().cpu().tolist()]

    def _text_embedding(self, text: str, torch, device):
        tokens = self._tokenizer([text]).to(device)
        with torch.no_grad():
            vector = self._model.encode_text(tokens)
            vector = vector / vector.norm(dim=-1, keepdim=True).clamp_min(1e-12)
        return [float(item) for item in vector[0].detach().cpu().tolist()]


class InsightFaceProvider(ExpansionOptionalProvider):
    def __init__(self, capability: str):
        super().__init__("insightface", capability, "buffalo_l")

    def _check_dependency(self):
        self._missing_dependency("insightface")

    def _load_model(self):
        self._check_dependency()
        from insightface.app import FaceAnalysis

        providers = [item for item in (os.environ.get("SPECIALIST_INSIGHTFACE_EXECUTION_PROVIDERS", "CPUExecutionProvider").split(",")) if item]
        self._app = FaceAnalysis(name=os.environ.get("SPECIALIST_INSIGHTFACE_MODEL", "buffalo_l"), providers=providers)
        self._app.prepare(ctx_id=0, det_size=(640, 640))

    def infer(self, input_path, options, cache):
        self.load()
        import cv2

        image = cv2.imread(str(input_path))
        if image is None:
            raise WorkerError("InsightFace could not read the input image", code="invalid_input", retryable=False)
        faces = self._app.get(image)
        if self.capability == "identity.face.detect":
            return {"faces": [_face_dict(face, index) for index, face in enumerate(faces)]}, []
        if self.capability == "identity.face.embed":
            if not faces:
                return {"embedding": None, "quality": 0.0, "status": "no_face"}, []
            embedding = faces[0].normed_embedding.tolist()
            quality = float(getattr(faces[0], "det_score", 0.0))
            path = _write_embedding(cache, embedding, self.model)
            return {"embedding": {"path": str(path), "dimension": len(embedding), "normalized": True, "model": self.model}, "embedding_path": str(path), "quality": quality}, []
        other_path = options.get("other_input")
        if not isinstance(other_path, str):
            raise WorkerError("identity.face.verify requires other_input", code="invalid_options", retryable=False)
        second_path = _resolve_file(other_path, cache, "other_input")
        second = cv2.imread(str(second_path))
        other_faces = self._app.get(second) if second is not None else []
        profile = str(options.get("profile", "balanced"))
        threshold = {"strict": 0.72, "balanced": 0.63, "loose": 0.55}.get(profile)
        if threshold is None:
            raise WorkerError("profile must be strict, balanced, or loose", code="invalid_options", retryable=False)
        if not faces or not other_faces:
            return {"match": False, "similarity": None, "threshold": threshold, "profile": profile, "status": "no_face"}, []
        similarity = _cosine(faces[0].normed_embedding.tolist(), other_faces[0].normed_embedding.tolist())
        return {"match": similarity >= threshold, "similarity": similarity, "threshold": threshold, "profile": profile, "status": "verified"}, []


def _face_dict(face, index):
    bbox = [round(float(value), 3) for value in face.bbox.tolist()]
    return {"id": f"face_{index}", "bbox": bbox, "confidence": float(getattr(face, "det_score", 0.0))}


def _write_embedding(cache, values, model, prefix="face-embedding"):
    cache.ensure_dirs()
    digest = hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()
    path = cache.results / f"{prefix}-{digest[:24]}.json"
    path.write_text(json.dumps({"vector": values, "dimension": len(values), "normalized": True, "model": model}, separators=(",", ":")), encoding="utf-8")
    return path


def _resolve_file(value, cache, field):
    if not isinstance(value, str) or not value.strip():
        raise WorkerError(f"{field} must be a local path or artifact:// URI", code="invalid_options", retryable=False)
    if value.startswith("artifact://"):
        try:
            root = getattr(cache, "artifacts", None) or Path(getattr(cache, "home", Path.home() / ".specialist")) / "artifacts"
            path = ArtifactStore(root).resolve(value)
        except (ArtifactError, OSError, ValueError) as exc:
            raise WorkerError(f"{field} artifact is unavailable: {exc}", code="invalid_artifact", retryable=False) from exc
    else:
        path = Path(value).expanduser()
    if not path.is_file():
        raise WorkerError(f"{field} file does not exist: {path}", code="input_not_found", retryable=False)
    if path.stat().st_size > 512 * 1024 * 1024:
        raise WorkerError(f"{field} exceeds the 512 MiB safety limit", code="input_too_large", retryable=False)
    return path


def _corpus_reference(item):
    if isinstance(item, str):
        return item, {}
    if isinstance(item, dict):
        reference = item.get("artifact") or item.get("path") or item.get("reference")
        if isinstance(reference, str):
            return reference, item
    raise WorkerError("corpus entries must be paths, artifact URIs, or objects containing path", code="invalid_options", retryable=False)


def optional_expansion_providers():
    providers = {}
    for capability in ("human.pose", "human.hand_landmarks", "human.face_landmarks", "human.gesture"):
        providers[capability] = MediaPipeProvider(capability)
    providers["speech.diarize"] = PyannoteProvider()
    providers["audio.denoise"] = DeepFilterNetProvider()
    for capability in ("vision.embed", "vision.embed_text", "vision.similarity", "vision.search"):
        providers[capability] = OpenCLIPProvider(capability)
    for capability in ("identity.face.detect", "identity.face.embed", "identity.face.verify"):
        providers[capability] = InsightFaceProvider(capability)
    return providers


OPTIONAL_EXPANSION_PROVIDERS = optional_expansion_providers()

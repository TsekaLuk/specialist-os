"""Fallback and deterministic providers for the capability expansion pack.

The fallback layer is intentionally honest: it performs deterministic work
where the runtime can do so safely and reports unavailable model inference
instead of returning fabricated detections or identities.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import wave
from pathlib import Path
from typing import Any

from ..geometry import GeometryError, angle, calibrate_camera, contour, distance, homography, match_features, polygon_area, solve_pnp, transform_points
from ..media import MediaError, audio_transform, concat, extract_audio, extract_frames, probe, transcode, trim_video
from .base import Provider
from .builtin import BuiltinProvider, image_dimensions
from .ipc import WorkerError


def _error(exc: Exception, default: str) -> WorkerError:
    code = getattr(exc, "code", default)
    return WorkerError(str(exc), code=code, retryable=False)


def _wav_info(path: Path) -> tuple[float | None, int | None, int | None]:
    try:
        with wave.open(str(path), "rb") as stream:
            rate = stream.getframerate()
            channels = stream.getnchannels()
            duration = stream.getnframes() / float(rate or 1)
            return duration, rate, channels
    except (OSError, EOFError, wave.Error):
        return None, None, None


def _stable_embedding(source: bytes, dimension: int = 64) -> list[float]:
    """Create a deterministic non-semantic vector for offline plumbing tests."""
    values: list[float] = []
    counter = 0
    while len(values) < dimension:
        digest = hashlib.sha256(source + counter.to_bytes(4, "big")).digest()
        values.extend((byte / 127.5) - 1.0 for byte in digest)
        counter += 1
    values = values[:dimension]
    norm = math.sqrt(sum(item * item for item in values)) or 1.0
    return [round(item / norm, 8) for item in values]


def _cosine(first: list[float], second: list[float]) -> float:
    if len(first) != len(second) or not first:
        raise ValueError("embeddings must have equal non-zero dimensions")
    return max(-1.0, min(1.0, sum(left * right for left, right in zip(first, second))))


class ExpansionFallbackProvider(BuiltinProvider):
    """Base class for expansion capabilities without optional model packages."""

    def __init__(self, name: str, capability: str, model: str = "fallback"):
        self.name = name
        self.capability = capability
        self.model = model

    def _unavailable(self, result: dict[str, Any], message: str | None = None):
        result.setdefault("status", "unavailable")
        warning = self._warning()[0]
        if message:
            warning = f"{warning} {message}"
        return result, [warning]

    def doctor(self, hardware):
        value = super().doctor(hardware)
        optional = {
            "mediapipe": ["mediapipe"],
            "pyannote": ["pyannote.audio", "torch"],
            "deepfilternet": ["df"],
            "openclip": ["open_clip", "torch", "Pillow"],
            "insightface": ["insightface"],
        }.get(self.name)
        if optional:
            value.update({"fallback": True, "optional_dependencies": optional, "capability_status": "unavailable_without_optional_provider"})
        return value


class HumanFallbackProvider(ExpansionFallbackProvider):
    def __init__(self, capability: str):
        super().__init__("mediapipe", capability, "mediapipe-tasks")

    def infer(self, input_path, options, cache):
        dimensions = image_dimensions(Path(input_path))
        if self.capability == "human.pose":
            return self._unavailable({"persons": [], "image": _dimensions(dimensions)})
        if self.capability == "human.hand_landmarks":
            return self._unavailable({"hands": [], "image": _dimensions(dimensions)})
        if self.capability == "human.face_landmarks":
            return self._unavailable({"faces": [], "image": _dimensions(dimensions)})
        return self._unavailable({"gesture": None, "confidence": None, "hand": None})


class DiarizeFallbackProvider(ExpansionFallbackProvider):
    def __init__(self):
        super().__init__("pyannote", "speech.diarize", "pyannote-community-1")

    def infer(self, input_path, options, cache):
        duration, sample_rate, channels = _wav_info(Path(input_path))
        return self._unavailable({"segments": [], "duration_seconds": round(duration or 0.0, 3), "sample_rate": sample_rate, "channels": channels})


class DenoiseFallbackProvider(ExpansionFallbackProvider):
    def __init__(self):
        super().__init__("deepfilternet", "audio.denoise", "deepfilternet-2")

    def infer(self, input_path, options, cache):
        profile = str(options.get("strength", options.get("profile", "balanced"))).lower()
        if profile not in {"light", "balanced", "strong"}:
            raise WorkerError("strength must be light, balanced, or strong", code="invalid_options", retryable=False)
        source = Path(input_path)
        duration, sample_rate, channels = _wav_info(source)
        cache.ensure_dirs()
        destination = cache.results / f"denoised-{cache.input_hash(source)[:16]}-{profile}.wav"
        shutil.copyfile(source, destination)
        result = {"audio": {"path": str(destination), "mime": "audio/wav", "duration_ms": round((duration or 0.0) * 1000, 3), "sample_rate": sample_rate, "channels": channels, "profile": profile, "processed": False}, "source_preserved": True, "profile": profile, "status": "passthrough"}
        return result, [self._warning()[0] + " Audio was preserved byte-for-byte because DeepFilterNet is not installed."]


class EmbeddingFallbackProvider(ExpansionFallbackProvider):
    def __init__(self, capability: str):
        super().__init__("openclip", capability, "siglip2-balanced")

    def _source(self, input_path: Path, options: dict[str, Any]) -> bytes:
        text = options.get("text")
        if isinstance(text, str):
            return text.encode("utf-8")
        return input_path.read_bytes()

    def infer(self, input_path, options, cache):
        if self.capability in {"vision.embed", "vision.embed_text"}:
            source = self._source(Path(input_path), options)
            vector = _stable_embedding(source)
            digest = hashlib.sha256(source).hexdigest()
            cache.ensure_dirs()
            path = cache.results / f"embedding-{digest[:24]}.json"
            path.write_text(json.dumps({"vector": vector, "dimension": len(vector), "normalized": True}, separators=(",", ":")), encoding="utf-8")
            return {"embedding": {"path": str(path), "dimension": len(vector), "normalized": True, "model": self.model, "status": "fallback-nonsemantic"}, "embedding_path": str(path), "dimension": len(vector), "normalized": True}, [self._warning()[0] + " The fallback vector is for contract testing, not semantic retrieval."]
        if self.capability == "vision.similarity":
            source = Path(input_path).read_bytes()
            vector = _stable_embedding(source)
            other = options.get("other_input")
            text = options.get("text")
            if other is None and text is None:
                raise WorkerError("vision.similarity requires other_input or text", code="invalid_options", retryable=False)
            if other is not None and text is not None:
                raise WorkerError("vision.similarity accepts either other_input or text, not both", code="invalid_options", retryable=False)
            if isinstance(text, str):
                if not text.strip():
                    raise WorkerError("text must be non-empty when supplied", code="invalid_options", retryable=False)
                other_source = text.encode("utf-8")
            else:
                other_path = Path(other).expanduser()
                if not other_path.is_file():
                    raise WorkerError(f"other_input file does not exist: {other_path}", code="input_not_found", retryable=False)
                other_source = other_path.read_bytes()
            other_vector = _stable_embedding(other_source)
            return {"score": _cosine(vector, other_vector), "metric": "cosine", "status": "fallback-nonsemantic"}, [self._warning()[0] + " Similarity uses the offline contract vector."]
        source = Path(input_path).read_bytes()
        vector = _stable_embedding(source)
        corpus = options.get("corpus")
        query = options.get("query")
        if not isinstance(corpus, list) or not corpus:
            raise WorkerError("vision.search requires a non-empty corpus array", code="invalid_options", retryable=False)
        query_vector = _stable_embedding(query.encode("utf-8")) if isinstance(query, str) else vector
        rows = []
        for item in corpus:
            path_value = item.get("path") if isinstance(item, dict) else item
            if not isinstance(path_value, str):
                continue
            candidate = Path(path_value).expanduser()
            if not candidate.is_file():
                continue
            candidate_vector = _stable_embedding(candidate.read_bytes())
            rows.append({"artifact": str(candidate), "score": _cosine(query_vector, candidate_vector), "metric": "cosine"})
        rows.sort(key=lambda item: (-item["score"], item["artifact"]))
        top_k = options.get("top_k", 20)
        if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 100:
            raise WorkerError("top_k must be an integer between 1 and 100", code="invalid_options", retryable=False)
        return {"results": rows[:top_k], "top_k": top_k, "metric": "cosine", "status": "fallback-nonsemantic"}, [self._warning()[0] + " Search uses the offline contract vector."]


class FaceFallbackProvider(ExpansionFallbackProvider):
    def __init__(self, capability: str):
        super().__init__("insightface", capability, "buffalo_l")

    def infer(self, input_path, options, cache):
        if self.capability == "identity.face.detect":
            return self._unavailable({"faces": []})
        if self.capability == "identity.face.embed":
            return self._unavailable({"embedding": None, "quality": None})
        profile = str(options.get("profile", "balanced"))
        threshold = {"strict": 0.72, "balanced": 0.63, "loose": 0.55}.get(profile)
        if threshold is None:
            raise WorkerError("profile must be strict, balanced, or loose", code="invalid_options", retryable=False)
        return self._unavailable({"match": None, "similarity": None, "threshold": threshold, "profile": profile, "status": "unavailable"}, "Face identity requires the local InsightFace provider.")


def _dimensions(value):
    return {"width": value[0], "height": value[1]} if value else None


class GeometryProvider(ExpansionFallbackProvider):
    def __init__(self, capability: str):
        super().__init__("opencv", capability, "opencv-5")

    def infer(self, input_path, options, cache):
        try:
            name = self.capability.rsplit(".", 1)[-1]
            if name == "distance":
                return distance(options.get("a"), options.get("b")), []
            if name == "angle":
                return angle(options.get("a"), options.get("vertex"), options.get("c"), options.get("unit", "degrees")), []
            if name == "area":
                return polygon_area(options.get("points")), []
            if name == "contour":
                return contour(options.get("points"), bool(options.get("closed", True))), []
            if name == "homography":
                return homography(options.get("source"), options.get("destination")), []
            if name == "perspective_transform":
                return transform_points(options.get("points"), options.get("matrix")), []
            if name == "calibrate_camera":
                return calibrate_camera(options.get("image_size"), options.get("object_points"), options.get("image_points")), []
            if name == "solve_pnp":
                return solve_pnp(options.get("object_points"), options.get("image_points"), options.get("camera_matrix"), options.get("distortion")), []
            if name == "match_features":
                return match_features(options.get("image_a") or input_path, options.get("image_b"), **options), []
            raise WorkerError(f"unsupported geometry operation: {name}", code="unsupported_operation", retryable=False)
        except WorkerError:
            raise
        except (GeometryError, TypeError, KeyError) as exc:
            raise _error(exc, "invalid_geometry") from exc


class TransformProvider(ExpansionFallbackProvider):
    def __init__(self, capability: str):
        super().__init__("opencv", capability, "opencv-5")

    def infer(self, input_path, options, cache):
        # ImageMagick is only invoked with arguments assembled from typed,
        # bounded options; arbitrary executable flags never cross this API.
        import subprocess

        source = Path(input_path)
        if not source.is_file():
            raise WorkerError(f"input file does not exist: {source}", code="input_not_found", retryable=False)
        operation = self.capability.rsplit(".", 1)[-1]
        destination = cache.results / f"transform-{cache.input_hash(source)[:16]}-{operation}.png"
        cache.ensure_dirs()
        if operation == "warp":
            return self._warp(source, destination, options)
        magick = shutil.which("magick")
        if not magick:
            raise WorkerError("Image transform operations require OpenCV or ImageMagick", code="dependency_missing", retryable=False)
        command = [magick, str(source)]
        if operation == "crop":
            width, height = _positive_int(options.get("width"), "width"), _positive_int(options.get("height"), "height")
            x, y = _nonnegative_int(options.get("x", 0), "x"), _nonnegative_int(options.get("y", 0), "y")
            command.extend(["-crop", f"{width}x{height}+{x}+{y}", "+repage"])
        elif operation == "resize":
            width, height = _positive_int(options.get("width"), "width"), _positive_int(options.get("height"), "height")
            command.extend(["-resize", f"{width}x{height}!"])
        elif operation == "rotate":
            degrees = _finite_number(options.get("degrees", 0), "degrees")
            if abs(degrees) > 3600:
                raise WorkerError("degrees must be between -3600 and 3600", code="invalid_options", retryable=False)
            command.extend(["-rotate", str(degrees), "-background", "none"])
        elif operation == "colorspace":
            colorspace = str(options.get("colorspace", "sRGB"))
            if colorspace not in {"sRGB", "Gray", "RGB", "CMYK"}:
                raise WorkerError("colorspace is not supported", code="invalid_options", retryable=False)
            command.extend(["-colorspace", colorspace])
        elif operation == "blur":
            sigma = _finite_number(options.get("sigma", 1), "sigma")
            if sigma < 0 or sigma > 100:
                raise WorkerError("sigma must be between 0 and 100", code="invalid_options", retryable=False)
            command.extend(["-blur", f"0x{sigma}"])
        elif operation == "threshold":
            percent = _finite_number(options.get("percent", 50), "percent")
            if percent < 0 or percent > 100:
                raise WorkerError("percent must be between 0 and 100", code="invalid_options", retryable=False)
            command.extend(["-threshold", f"{percent}%"])
        command.append(str(destination))
        completed = subprocess.run(command, capture_output=True, text=True, timeout=300, check=False)
        if completed.returncode:
            raise WorkerError((completed.stderr or "image transform failed").strip(), code="transform_failed", retryable=False)
        return {"image_path": str(destination), "operation": operation, "deterministic": True}, []

    def _warp(self, source: Path, destination: Path, options: dict[str, Any]):
        matrix = options.get("matrix")
        if not isinstance(matrix, (list, tuple)) or len(matrix) != 3 or any(not isinstance(row, (list, tuple)) or len(row) != 3 for row in matrix):
            raise WorkerError("matrix must be a 3x3 array", code="invalid_options", retryable=False)
        parsed = [[_finite_number(value, f"matrix[{row}][{column}]") for column, value in enumerate(values)] for row, values in enumerate(matrix)]
        try:
            import cv2
            import numpy as np
        except ImportError as exc:
            raise WorkerError("vision.transform.warp requires OpenCV; install the vision-operators pack with dependencies", code="dependency_missing", retryable=False) from exc
        image = cv2.imread(str(source), cv2.IMREAD_UNCHANGED)
        if image is None:
            raise WorkerError("OpenCV could not read the input image", code="invalid_input", retryable=False)
        height, width = image.shape[:2]
        output_width = _positive_int(options.get("width", width), "width")
        output_height = _positive_int(options.get("height", height), "height")
        if output_width * output_height > 100_000_000:
            raise WorkerError("warped image cannot exceed 100 million pixels", code="invalid_options", retryable=False)
        try:
            warped = cv2.warpPerspective(image, np.asarray(parsed, dtype=np.float64), (output_width, output_height))
            written = cv2.imwrite(str(destination), warped)
        except cv2.error as exc:
            raise WorkerError(f"OpenCV warp failed: {exc}", code="transform_failed", retryable=False) from exc
        if not written:
            raise WorkerError("OpenCV could not write the warped image", code="transform_failed", retryable=False)
        return {"image_path": str(destination), "operation": "warp", "width": output_width, "height": output_height, "deterministic": True}, []


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise WorkerError(f"{field} must be a finite number", code="invalid_options", retryable=False)
    return float(value)


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0 or value > 100_000:
        raise WorkerError(f"{field} must be a positive integer", code="invalid_options", retryable=False)
    return value


def _nonnegative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 100_000:
        raise WorkerError(f"{field} must be a non-negative integer", code="invalid_options", retryable=False)
    return value


class MediaProvider(ExpansionFallbackProvider):
    def __init__(self, capability: str):
        super().__init__("ffmpeg", capability, "ffmpeg-9")

    def infer(self, input_path, options, cache):
        try:
            operation = self.capability
            if operation == "media.probe":
                return probe(input_path), []
            if operation == "media.video.extract_frames":
                return extract_frames(input_path, cache.results, fps=options.get("fps"), timestamps=options.get("timestamps"), timeout=options.get("timeout_seconds", 300)), []
            if operation == "media.video.trim":
                return trim_video(input_path, cache.results, options.get("start"), options.get("end"), options.get("timeout_seconds", 900)), []
            if operation == "media.video.transcode":
                return transcode(input_path, cache.results, format=options.get("format", "mp4"), video_codec=options.get("video_codec"), audio_codec=options.get("audio_codec"), timeout=options.get("timeout_seconds", 900)), []
            if operation == "media.video.concat":
                return concat(options.get("inputs"), cache.results, timeout=options.get("timeout_seconds", 900)), []
            if operation == "media.audio.extract":
                return extract_audio(input_path, cache.results, timeout=options.get("timeout_seconds", 900)), []
            if operation == "media.audio.trim":
                start, end = options.get("start"), options.get("end")
                return _audio_trim(input_path, cache.results, start, end, options.get("timeout_seconds", 900)), []
            if operation in {"media.audio.resample", "media.audio.convert", "media.audio.normalize"}:
                return audio_transform(input_path, cache.results, operation.rsplit(".", 1)[-1], sample_rate=options.get("sample_rate"), channels=options.get("channels"), format=options.get("format", "wav"), timeout=options.get("timeout_seconds", 900)), []
            raise WorkerError(f"unsupported media operation: {operation}", code="unsupported_operation", retryable=False)
        except WorkerError:
            raise
        except MediaError as exc:
            raise _error(exc, "media_error") from exc


def _audio_trim(input_path, output_root, start, end, timeout):
    from ..media import _time

    start_value = _time(start, "start")
    end_value = _time(end, "end")
    if end_value <= start_value:
        raise MediaError("end must be greater than start and start must be non-negative")
    source = Path(input_path)
    destination = output_root / f"{source.stem}-trim-{hashlib.sha256(f'{start_value}:{end_value}'.encode()).hexdigest()[:12]}.wav"
    output_root.mkdir(parents=True, exist_ok=True)
    from ..media import _run, _executable

    _run([_executable("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-ss", str(start_value), "-to", str(end_value), "-i", str(source), "-vn", "-c:a", "pcm_s16le", str(destination)], timeout=timeout)
    return {"audio_path": str(destination), "mime": "audio/wav", "start": start_value, "end": end_value, "deterministic": True}


class CompositeProvider(ExpansionFallbackProvider):
    composite = True

    def __init__(self, capability: str):
        super().__init__("composite", capability, "runtime-composite-1")
        self.runtime = None

    def infer(self, input_path, options, cache):
        if self.runtime is None:
            raise WorkerError("composite provider is not bound to a runtime", code="provider_not_configured", retryable=False)
        if self.capability == "speech.align_transcript":
            transcript = options.get("transcript", [])
            diarization = options.get("diarization", options.get("segments", []))
            return {"segments": align_transcript(transcript, diarization), "deterministic": True}, []
        if self.capability == "speech.meeting":
            return self._meeting(input_path, options)
        if self.capability == "vision.human_state":
            return self._human_state(input_path, options)
        if self.capability == "vision.find_similar":
            result = self.runtime.run("vision.search", input_path, options)
            if result.get("error"):
                error = result["error"]
                raise WorkerError(error.get("message", "vision.search failed"), code=error.get("code", "child_capability_failed"), retryable=bool(error.get("retryable", False)))
            return _composite_result(result, "vision.search"), []
        if self.capability == "vision.face_compare":
            result = self.runtime.run("identity.face.verify", input_path, options)
            if result.get("error"):
                error = result["error"]
                raise WorkerError(error.get("message", "identity.face.verify failed"), code=error.get("code", "child_capability_failed"), retryable=bool(error.get("retryable", False)))
            return _composite_result(result, "identity.face.verify"), []
        if self.capability == "media.transcribe_video":
            return self._transcribe_video(input_path, options)
        if self.capability == "vision.measure":
            return self._measure(input_path, options)
        raise WorkerError(f"unsupported composite: {self.capability}", code="unsupported_operation", retryable=False)

    def _meeting(self, input_path, options):
        child_options = {key: value for key, value in options.items() if key not in {"transcript", "diarization"}}
        denoise = self.runtime.run("audio.denoise", input_path, {"strength": options.get("strength", "balanced")})
        denoise_path = _artifact_input(self.runtime, denoise, input_path)
        vad = self.runtime.run("audio.vad", denoise_path, child_options)
        transcript = self.runtime.run("audio.transcribe", denoise_path, child_options)
        diarize = self.runtime.run("speech.diarize", denoise_path, child_options)
        aligned = align_transcript((transcript.get("result") or {}).get("segments", []), (diarize.get("result") or {}).get("segments", []))
        children = [denoise, vad, transcript, diarize]
        result = {"segments": aligned, "audio": {"denoise": denoise.get("result"), "vad": vad.get("result")}, "deterministic": False, "status": _composite_status([denoise, vad, transcript, diarize])}
        return {**result, "_trace": _child_trace(children), "_child_artifacts": _child_artifacts(children), "_child_provenance": _child_provenance(children)}, _child_warnings(children)

    def _human_state(self, input_path, options):
        children = [self.runtime.run(name, input_path, options) for name in ("vision.detect", "human.pose", "human.hand_landmarks", "human.face_landmarks", "vision.depth")]
        return {"detection": children[0].get("result"), "pose": children[1].get("result"), "hands": children[2].get("result"), "face": children[3].get("result"), "depth": children[4].get("result"), "status": _composite_status(children), "_trace": _child_trace(children), "_child_artifacts": _child_artifacts(children), "_child_provenance": _child_provenance(children)}, _child_warnings(children)

    def _transcribe_video(self, input_path, options):
        extracted = self.runtime.run("media.audio.extract", input_path, options)
        audio_path = _artifact_input(self.runtime, extracted, input_path)
        denoise = self.runtime.run("audio.denoise", audio_path, {"strength": options.get("strength", "balanced")})
        denoised_path = _artifact_input(self.runtime, denoise, audio_path)
        transcript = self.runtime.run("audio.transcribe", denoised_path, options)
        children = [extracted, denoise, transcript]
        diarize = None
        if options.get("diarize", False):
            diarize = self.runtime.run("speech.diarize", denoised_path, options)
            children.append(diarize)
        segments = (transcript.get("result") or {}).get("segments", [])
        if diarize:
            segments = align_transcript(segments, (diarize.get("result") or {}).get("segments", []))
        return {"text": (transcript.get("result") or {}).get("text", ""), "segments": segments, "status": _composite_status(children), "_trace": _child_trace(children), "_child_artifacts": _child_artifacts(children), "_child_provenance": _child_provenance(children)}, _child_warnings(children)

    def _measure(self, input_path, options):
        detect = self.runtime.run("vision.detect", input_path, options)
        depth_mode = str(options.get("mode", "relative")).lower()
        depth = self.runtime.run("vision.depth", input_path, {**options, "mode": depth_mode})
        points_value = options.get("points")
        geometry = None
        if points_value:
            geometry = self.runtime.run("vision.geometry.distance", input_path, {"a": points_value[0], "b": points_value[1]})
        children = [detect, depth] + ([geometry] if geometry else [])
        metric_estimate = depth_mode == "metric" and not bool(depth.get("error"))
        return {"detections": (detect.get("result") or {}).get("items", []), "depth": depth.get("result"), "measurement": geometry.get("result") if geometry else None, "mode": depth_mode, "estimated": metric_estimate, "status": _composite_status(children), "_trace": _child_trace(children), "_child_artifacts": _child_artifacts(children), "_child_provenance": _child_provenance(children)}, _child_warnings(children)


def _artifact_input(runtime, envelope, fallback):
    result = envelope.get("result") or {}
    audio = result.get("audio") if isinstance(result, dict) else None
    value = audio.get("artifact") if isinstance(audio, dict) else None
    if isinstance(value, str) and value.startswith("artifact://"):
        try:
            return runtime.artifacts.resolve(value)
        except Exception:
            pass
    for key in ("audio_path", "media_path"):
        value = result.get(key) if isinstance(result, dict) else None
        if not isinstance(value, str):
            continue
        if value.startswith("artifact://"):
            try:
                return runtime.artifacts.resolve(value)
            except Exception:
                continue
        if Path(value).is_file():
            return value
    return fallback


def align_transcript(transcript: Any, diarization: Any) -> list[dict[str, Any]]:
    if not isinstance(transcript, list) or not isinstance(diarization, list):
        raise WorkerError("transcript and diarization must be arrays", code="invalid_options", retryable=False)
    output = []
    for item in transcript:
        if not isinstance(item, dict):
            continue
        start, end = _interval(item.get("start"), item.get("end"))
        matches = []
        for speaker in diarization:
            if not isinstance(speaker, dict):
                continue
            speaker_start, speaker_end = _interval(speaker.get("start"), speaker.get("end"))
            overlap = max(0.0, min(end, speaker_end) - max(start, speaker_start))
            if overlap > 0:
                matches.append((overlap, str(speaker.get("speaker") or speaker.get("label") or "speaker_0")))
        matches.sort(key=lambda item: (-item[0], item[1]))
        output.append({"speaker": matches[0][1] if matches else "unknown", "start": start, "end": end, "text": str(item.get("text", "")), "confidence": item.get("confidence")})
    return output


def _interval(start: Any, end: Any) -> tuple[float, float]:
    try:
        first, second = float(start), float(end)
    except (TypeError, ValueError) as exc:
        raise WorkerError("timeline segments require numeric start and end", code="invalid_options", retryable=False) from exc
    if not math.isfinite(first) or not math.isfinite(second) or first < 0 or second < first:
        raise WorkerError("timeline segment has an invalid time range", code="invalid_options", retryable=False)
    return first, second


def _child_trace(children):
    return [{"capability": item.get("capability"), "provider": item.get("provider"), "model": item.get("model"), "error": item.get("error"), "status": "error" if item.get("error") else "completed"} for item in children]


def _composite_status(children):
    for item in children:
        if not isinstance(item, dict) or item.get("error"):
            return "degraded"
        result = item.get("result")
        if isinstance(result, dict) and result.get("status") == "unavailable":
            return "degraded"
    return "completed"


def _child_artifacts(children):
    values = []
    for item in children:
        for artifact in item.get("artifacts", []) if isinstance(item, dict) else []:
            if isinstance(artifact, dict) and artifact.get("id") and not any(existing.get("id") == artifact.get("id") for existing in values):
                values.append(artifact)
    return values


def _child_provenance(children):
    return [item.get("provenance") for item in children if isinstance(item, dict) and isinstance(item.get("provenance"), dict)]


def _child_warnings(children):
    return [warning for item in children for warning in item.get("warnings", []) if isinstance(warning, str)]


def _composite_result(envelope, source):
    result = dict(envelope.get("result") or {})
    result["source_capability"] = source
    result["source_result"] = envelope.get("result")
    result["_trace"] = _child_trace([envelope])
    result["_child_artifacts"] = _child_artifacts([envelope])
    result["_child_provenance"] = _child_provenance([envelope])
    return result


def expansion_builtin_providers():
    providers: dict[str, Provider] = {}
    for capability in ("human.pose", "human.hand_landmarks", "human.face_landmarks", "human.gesture"):
        providers[capability] = HumanFallbackProvider(capability)
    providers["speech.diarize"] = DiarizeFallbackProvider()
    providers["audio.denoise"] = DenoiseFallbackProvider()
    for capability in ("vision.embed", "vision.embed_text", "vision.similarity", "vision.search"):
        providers[capability] = EmbeddingFallbackProvider(capability)
    for capability in ("identity.face.detect", "identity.face.embed", "identity.face.verify"):
        providers[capability] = FaceFallbackProvider(capability)
    geometry_names = ("distance", "angle", "area", "contour", "homography", "match_features", "perspective_transform", "calibrate_camera", "solve_pnp")
    for name in geometry_names:
        providers[f"vision.geometry.{name}"] = GeometryProvider(f"vision.geometry.{name}")
    for name in ("crop", "resize", "rotate", "warp", "colorspace", "blur", "threshold"):
        providers[f"vision.transform.{name}"] = TransformProvider(f"vision.transform.{name}")
    for capability in ("media.probe", "media.video.extract_frames", "media.video.trim", "media.video.transcode", "media.video.concat", "media.audio.extract", "media.audio.trim", "media.audio.resample", "media.audio.convert", "media.audio.normalize"):
        providers[capability] = MediaProvider(capability)
    for capability in ("speech.align_transcript", "speech.meeting", "vision.human_state", "vision.find_similar", "vision.face_compare", "media.transcribe_video", "vision.measure"):
        providers[capability] = CompositeProvider(capability)
    return providers


EXPANSION_PROVIDERS = expansion_builtin_providers()

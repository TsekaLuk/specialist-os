"""Fish Audio and genuine local system-TTS adapters.

The Fish adapter speaks only to the upstream HTTP server. It deliberately has
no import-time dependency on Fish Speech, PyTorch, CUDA or audio frameworks.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import wave

from ...artifacts import ArtifactError, ArtifactStore
from ...voices import VoiceRegistry, VoiceRegistryError
from ..ipc import WorkerError
from .client import FishAudioClient, FishAudioError
from .lifecycle import FishAudioLifecycle


def _audio_metadata(path: Path, raw_metadata: dict, mime: str) -> dict:
    metadata = {"mime": mime, **{key: value for key, value in raw_metadata.items() if key in {"duration_ms", "sample_rate"}}}
    if mime in {"audio/wav", "audio/x-wav"} or path.suffix.lower() == ".wav":
        try:
            with wave.open(str(path), "rb") as audio:
                metadata.setdefault("sample_rate", audio.getframerate())
                metadata.setdefault("duration_ms", round(audio.getnframes() * 1000 / float(audio.getframerate() or 1)))
        except (OSError, EOFError, wave.Error) as exc:
            raise WorkerError(f"generated audio is not a valid WAV file: {exc}", code="malformed_audio", retryable=False) from exc
    elif mime in {"audio/mpeg", "audio/mp3"}:
        header = path.read_bytes()[:3]
        if not (header.startswith(b"ID3") or (len(header) >= 2 and header[0] == 0xFF and header[1] & 0xE0 == 0xE0)):
            raise WorkerError("generated audio is not a valid MPEG stream", code="malformed_audio", retryable=False)
    elif mime in {"audio/ogg", "audio/opus"} and path.read_bytes()[:4] != b"OggS":
        raise WorkerError("generated audio is not a valid Ogg stream", code="malformed_audio", retryable=False)
    elif mime == "audio/flac" and path.read_bytes()[:4] != b"fLaC":
        raise WorkerError("generated audio is not a valid FLAC stream", code="malformed_audio", retryable=False)
    elif mime in {"audio/aiff", "audio/x-aiff"}:
        header = path.read_bytes()[:12]
        if len(header) < 12 or header[:4] != b"FORM" or header[8:12] not in {b"AIFF", b"AIFC"}:
            raise WorkerError("generated audio is not a valid AIFF stream", code="malformed_audio", retryable=False)
    if not path.is_file() or path.stat().st_size == 0:
        raise WorkerError("generated audio is empty", code="malformed_audio", retryable=False)
    metadata.setdefault("sample_rate", None)
    metadata.setdefault("duration_ms", None)
    return metadata


class FishAudioProvider:
    name = "fish_audio"
    preferred_model = "s2-pro"
    supported_platforms = ("linux-x64", "windows-x64", "macos-arm64")
    supported_devices = ("cuda", "cpu", "mps")
    memory_requirement_mb = 24576
    disk_requirement_mb = 0
    license = "Fish Audio Research License"
    commercial = False
    requires_verified_artifact = False
    requires_provider_environment = False
    requires_local_model_directory = False
    # S2 weights and GPU memory belong to the operator-managed Fish server.
    # Specialist Core only manages the authenticated protocol boundary.
    server_managed = True
    max_concurrency = 1
    quality = 0.98
    # Warm-server estimate; cold startup is represented separately by the
    # lifecycle trace and the heavy model resource profile.
    latency_ms = 500

    def __init__(self, capability: str = "speech.synthesize", model: str = "s2-pro"):
        self.capability = capability
        self.model = model
        self._loaded = False
        self._cache = None
        self._lifecycle: FishAudioLifecycle | None = None

    def _config(self):
        endpoint = os.environ.get("SPECIALIST_FISH_AUDIO_URL", "http://127.0.0.1:8080")
        token = os.environ.get("SPECIALIST_FISH_AUDIO_TOKEN")
        policy = os.environ.get("SPECIALIST_FISH_AUDIO_START_POLICY", "on-demand")
        try:
            startup = float(os.environ.get("SPECIALIST_FISH_AUDIO_STARTUP_TIMEOUT", "180"))
        except ValueError:
            startup = 180.0
        return endpoint, token, policy, startup

    def _get_lifecycle(self) -> FishAudioLifecycle:
        if self._lifecycle is None:
            endpoint, token, policy, startup = self._config()
            home = Path(getattr(self._cache, "home", os.environ.get("SPECIALIST_HOME", Path.home() / ".specialist"))).expanduser()
            self._lifecycle = FishAudioLifecycle(FishAudioClient(endpoint, token=token, timeout_seconds=900), start_policy=policy, startup_timeout=startup, state_path=home / "metadata" / "fish_audio.lifecycle.json")
        return self._lifecycle

    @property
    def lifecycle(self) -> FishAudioLifecycle:
        return self._get_lifecycle()

    @property
    def remote(self) -> bool:
        return self._get_lifecycle().client.is_remote

    def install(self, cache, spec):
        self._cache = cache
        marker = cache.mark_installed(spec.name, self.name, getattr(self, "model", spec.model), status="ready", license_name=spec.license, source="fish-audio-server", commercial=spec.commercial, source_url=spec.source_url, server_endpoint=self._get_lifecycle().client.endpoint, start_policy=self._get_lifecycle().start_policy, max_concurrency=self.max_concurrency)
        return {"status": "ready", "downloaded": False, "backend": "fish-audio-server", "server": self._get_lifecycle().client.endpoint, "license_mode": "research_only" if not spec.commercial else "commercial"}

    def doctor(self, hardware):
        lifecycle = self._get_lifecycle()
        value = lifecycle.health()
        is_macos = str(hardware.get("os", "")).lower().startswith("darwin")
        suitable = bool(hardware.get("cuda") and (hardware.get("memory_gb") or 0) >= 24)
        value.update({"backend": "isolated-http-server", "provider": self.name, "model": self.model, "hardware": hardware, "support_level": "experimental" if is_macos else "supported", "hardware_suitable": suitable, "recommended_gpu_memory_gb": 24, "license_mode": "research_only", "max_concurrency": self.max_concurrency})
        if is_macos:
            value["recommended_execution"] = "remote GPU node"
        elif hardware.get("cuda"):
            value["recommended_execution"] = "local CUDA"
        else:
            value["recommended_execution"] = "remote GPU node"
        return value

    def load(self):
        self._get_lifecycle().ensure_ready()
        self._loaded = True
        return self

    def unload(self):
        # The server is intentionally kept warm. Lifecycle stop is explicit.
        self._loaded = False
        return None

    def close(self):
        # A child started by on-demand mode belongs to this runtime. An
        # operator-managed or always-on server is never terminated here.
        lifecycle = self._get_lifecycle()
        if lifecycle.process is not None and lifecycle.start_policy != "always-on":
            lifecycle.stop()

    @staticmethod
    def _text(input_path: Path, options: dict) -> str:
        value = options.get("text")
        if value is None:
            try:
                value = input_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                raise WorkerError(f"speech text cannot be read: {exc}", code="invalid_speech_text", retryable=False) from exc
        if not isinstance(value, str) or not value.strip():
            raise WorkerError("speech text must be a non-empty string", code="invalid_speech_text", retryable=False)
        return value

    def _voice(self, value: str | None, cache):
        if not value:
            return None, None
        if not isinstance(value, str) or not value.startswith("voice://"):
            raise WorkerError("voice must use the voice:// URI form", code="invalid_voice", retryable=False)
        root = Path(getattr(cache, "home", Path.home() / ".specialist")) / "voices"
        registry = VoiceRegistry(root, ArtifactStore(Path(getattr(cache, "home", Path.home() / ".specialist")) / "artifacts"))
        try:
            record = registry.require(value)
            path = registry.artifact_path(record)
        except VoiceRegistryError as exc:
            raise WorkerError(str(exc), code="voice_not_found", retryable=False) from exc
        assets = record.get("provider_assets") or {}
        fish = assets.get("fish_audio") if isinstance(assets, dict) else None
        reference_id = fish.get("reference_id") if isinstance(fish, dict) else None
        return reference_id, path

    @staticmethod
    def _reference_path(value, cache) -> Path:
        """Resolve a local reference or an Artifact URI inside the worker."""
        if isinstance(value, str) and value.startswith("artifact://"):
            try:
                path = ArtifactStore(Path(getattr(cache, "home", Path.home() / ".specialist")) / "artifacts").resolve(value)
            except (ArtifactError, OSError) as exc:
                raise WorkerError(f"reference audio artifact is unavailable: {exc}", code="reference_audio_unavailable", retryable=False) from exc
        else:
            try:
                path = Path(value).expanduser()
            except TypeError as exc:
                raise WorkerError("reference audio must be a local path or artifact:// URI", code="reference_audio_unavailable", retryable=False) from exc
        if path.is_symlink() or not path.is_file():
            raise WorkerError(f"reference audio is not a regular file: {path}", code="reference_audio_unavailable", retryable=False)
        return path

    def infer(self, input_path, options, cache):
        self._cache = cache
        self.load()
        options = dict(options or {})
        provider_options = options.get("provider_options", {}).get("fish_audio", {}) if isinstance(options.get("provider_options"), dict) else {}
        if provider_options is None:
            provider_options = {}
        if not isinstance(provider_options, dict):
            raise WorkerError("provider_options.fish_audio must be an object", code="invalid_provider_options", retryable=False)
        reference_id, voice_path = self._voice(options.get("voice"), cache)
        reference_audio = None
        if self.capability == "speech.clone_voice":
            # A provider-specific reference_id is already resident on the
            # Fish server. Reuse it directly and keep the local source audio
            # inside the trusted boundary; otherwise resolve and send the
            # caller's reference artifact.
            if not reference_id:
                reference_audio = voice_path or self._reference_path(options.get("reference_audio") or input_path, cache)
            if reference_audio is not None and self.lifecycle.client.is_remote and not bool(options.get("allow_remote") or os.environ.get("SPECIALIST_PRIVACY_ALLOW_REMOTE") == "1"):
                raise WorkerError("reference audio cannot be sent to a remote provider without privacy.allow_remote=true", code="privacy_remote_disabled", retryable=False)
        elif voice_path is not None and reference_id is None:
            reference_audio = voice_path
            if self.lifecycle.client.is_remote and not bool(options.get("allow_remote") or os.environ.get("SPECIALIST_PRIVACY_ALLOW_REMOTE") == "1"):
                raise WorkerError("voice reference audio cannot be sent to a remote provider without privacy.allow_remote=true", code="privacy_remote_disabled", retryable=False)
        try:
            audio, mime, metadata = self.lifecycle.client.synthesize(
                text=self._text(Path(input_path), options),
                format=str((options.get("audio") or {}).get("format") or options.get("format") or "wav"),
                language=options.get("language"),
                style=options.get("style"),
                reference_id=reference_id or options.get("reference_id"),
                reference_audio=reference_audio,
                reference_text=options.get("reference_text"),
                stream=bool(options.get("stream", False)),
                provider_options=provider_options,
                timeout=float(options.get("timeout_seconds", 900)),
            )
        except FishAudioError as exc:
            raise WorkerError(str(exc), code=exc.code, retryable=exc.retryable) from exc
        suffix = ".wav" if mime in {"audio/wav", "audio/x-wav"} else ".bin"
        root = Path(getattr(cache, "home", Path.home() / ".specialist")) / "artifacts" / ".tmp"
        root.mkdir(parents=True, exist_ok=True)
        try:
            root.chmod(0o700)
        except OSError:
            pass
        with tempfile.NamedTemporaryFile("wb", suffix=suffix, prefix="fish-audio-", dir=root, delete=False) as stream:
            stream.write(audio)
            generated = Path(stream.name)
        try:
            audio_metadata = _audio_metadata(generated, metadata, mime)
        except Exception:
            generated.unlink(missing_ok=True)
            raise
        audio_metadata.update({"path": str(generated), "temporary": True})
        voice = options.get("voice") or ("reference" if reference_audio else None)
        result = {"audio": audio_metadata, "voice": voice, "server": self.lifecycle.client.endpoint}
        warnings = []
        if options.get("language"):
            warnings.append("Fish Audio detects language from the input text")
        if options.get("stream"):
            result["streaming"] = {"mode": "complete_then_chunk", "chunked": False}
        return result, warnings


class SystemTTSProvider:
    """Real OS TTS fallback using espeak-ng/espeak or macOS say."""

    name = "system_tts"
    capability = "speech.synthesize"
    model = "system-default"
    preferred_model = "system-default"
    supported_platforms = ("linux-x64", "macos-arm64", "windows-x64")
    supported_devices = ("cpu",)
    memory_requirement_mb = 128
    disk_requirement_mb = 0
    license = "system voice terms"
    commercial = True
    requires_verified_artifact = False
    quality = 0.35
    latency_ms = 300

    def __init__(self):
        self._loaded = False

    def _binary(self):
        return shutil.which("espeak-ng") or shutil.which("espeak") or shutil.which("say")

    def install(self, cache, spec):
        binary = self._binary()
        cache.mark_installed(spec.name, self.name, self.model, status="ready", license_name=self.license, source="system", commercial=True)
        return {"status": "ready" if binary else "available", "downloaded": False, "backend": "system", "binary": binary}

    def doctor(self, hardware):
        binary = self._binary()
        return {"status": "ready" if binary else "not ready", "backend": "system", "binary": binary, "hardware": hardware, "error": None if binary else {"code": "system_tts_missing", "message": "Install espeak-ng/espeak or use macOS say"}}

    def load(self):
        if not self._binary():
            raise WorkerError("no system TTS executable found (espeak-ng, espeak or say)", code="system_tts_missing", retryable=False)
        self._loaded = True
        return self

    def unload(self):
        self._loaded = False

    def infer(self, input_path, options, cache):
        self.load()
        text = options.get("text")
        if text is None:
            text = Path(input_path).read_text(encoding="utf-8")
        if not isinstance(text, str) or not text.strip():
            raise WorkerError("speech text must be a non-empty string", code="invalid_speech_text", retryable=False)
        binary = self._binary()
        root = Path(getattr(cache, "home", Path.home() / ".specialist")) / "artifacts" / ".tmp"
        root.mkdir(parents=True, exist_ok=True)
        target_handle, target_name = tempfile.mkstemp(prefix="system-tts-", suffix=".wav", dir=root)
        os.close(target_handle)
        target = Path(target_name)
        target.unlink(missing_ok=True)
        source_target = target
        try:
            if Path(binary).name in {"espeak", "espeak-ng"}:
                command = [binary, "-w", str(target)]
                if options.get("language"):
                    command.extend(["-v", str(options["language"])])
                command.append(text)
            else:
                # macOS ``say`` emits AIFF when given a normal output path.
                # Convert to the requested WAV contract when ffmpeg exists.
                source_handle, source_name = tempfile.mkstemp(prefix="system-tts-", suffix=".aiff", dir=root)
                os.close(source_handle)
                source_target = Path(source_name)
                source_target.unlink(missing_ok=True)
                command = [binary, "-o", str(source_target), text]
            completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=float(options.get("timeout_seconds", 900)), check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise WorkerError(f"system TTS failed: {exc}", code="system_tts_failed", retryable=True) from exc
        if completed.returncode != 0:
            raise WorkerError((completed.stderr or "system TTS failed").strip(), code="system_tts_failed", retryable=False)
        mime = "audio/wav"
        if source_target != target:
            ffmpeg = shutil.which("ffmpeg")
            if ffmpeg:
                converted = subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(source_target), str(target)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=float(options.get("timeout_seconds", 900)), check=False)
                source_target.unlink(missing_ok=True)
                if converted.returncode != 0:
                    raise WorkerError((converted.stderr or "audio conversion failed").strip(), code="system_tts_failed", retryable=False)
            else:
                target = source_target
                mime = "audio/aiff"
        try:
            metadata = _audio_metadata(target, {}, mime)
        except Exception:
            target.unlink(missing_ok=True)
            if source_target != target:
                source_target.unlink(missing_ok=True)
            raise
        metadata.update({"path": str(target), "temporary": True})
        return {"audio": metadata, "voice": options.get("voice")}, []

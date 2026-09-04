"""Small dependency-free client for the Fish Audio server contract."""

from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path
import urllib.error
from urllib.parse import urlsplit
import urllib.request


class FishAudioError(RuntimeError):
    def __init__(self, message: str, *, code: str = "fish_audio_error", retryable: bool = True):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class FishAudioClient:
    def __init__(self, endpoint: str, *, token: str | None = None, timeout_seconds: float = 900, max_audio_bytes: int = 512 * 1024 * 1024):
        endpoint = str(endpoint).rstrip("/")
        parsed = urlsplit(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Fish Audio endpoint must be an http(s) URL")
        self.endpoint = endpoint
        self.token = token
        self.timeout_seconds = float(timeout_seconds)
        self.max_audio_bytes = max(1, int(max_audio_bytes))

    @property
    def is_remote(self) -> bool:
        host = (urlsplit(self.endpoint).hostname or "").lower()
        return host not in {"127.0.0.1", "localhost", "::1"}

    def _request(self, path: str, *, method: str = "GET", payload: dict | None = None, timeout: float | None = None):
        body = None
        headers = {"Accept": "application/json, audio/*", "User-Agent": "specialist-runtime/fish-audio"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(f"{self.endpoint}{path}", data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout_seconds) as response:
                raw = response.read(self.max_audio_bytes + 1)
                if len(raw) > self.max_audio_bytes:
                    raise FishAudioError("Fish Audio response exceeds the audio safety limit", code="fish_audio_output_too_large", retryable=False)
                return response.status, response.headers, raw
        except urllib.error.HTTPError as exc:
            detail = exc.read(4096).decode("utf-8", errors="replace")
            retryable = exc.code >= 500 or exc.code == 429
            raise FishAudioError(f"Fish Audio server returned HTTP {exc.code}: {detail[:500]}", code="fish_audio_http_error", retryable=retryable) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise FishAudioError(f"Fish Audio server is unreachable: {exc}", code="fish_audio_unreachable", retryable=True) from exc

    def health(self, timeout: float = 5) -> dict:
        status, _headers, raw = self._request("/v1/health", timeout=timeout)
        if status != 200:
            raise FishAudioError(f"Fish Audio health returned HTTP {status}", code="fish_audio_unhealthy")
        try:
            value = json.loads(raw or b"{}")
        except ValueError as exc:
            raise FishAudioError("Fish Audio health response is not JSON", code="fish_audio_protocol_error", retryable=False) from exc
        if not isinstance(value, dict) or str(value.get("status", "")).lower() not in {"ok", "ready", "healthy"}:
            raise FishAudioError("Fish Audio server is not ready", code="fish_audio_unhealthy")
        return value

    def synthesize(self, *, text: str, format: str = "wav", language: str | None = None, style: dict | str | None = None, reference_id: str | None = None, reference_audio: Path | None = None, reference_text: str | None = None, stream: bool = False, provider_options: dict | None = None, timeout: float | None = None) -> tuple[bytes, str, dict]:
        if not isinstance(text, str) or not text.strip():
            raise FishAudioError("speech text must be a non-empty string", code="invalid_speech_text", retryable=False)
        output_format = str(format).strip().lower()
        if output_format not in {"wav", "mp3", "ogg", "flac"}:
            raise FishAudioError("audio format must be wav, mp3, ogg or flac", code="invalid_audio_format", retryable=False)
        payload: dict = {"text": text, "format": output_format, "stream": bool(stream)}
        if language:
            payload["language"] = language
        if style:
            payload["style"] = style
        if reference_id:
            payload["reference_id"] = reference_id
        if reference_text:
            payload["reference_text"] = reference_text
        if reference_audio is not None:
            reference_audio = Path(reference_audio).expanduser()
            if reference_audio.is_symlink() or not reference_audio.is_file():
                raise FishAudioError(f"reference audio is not a regular file: {reference_audio}", code="reference_audio_unavailable", retryable=False)
            try:
                if reference_audio.stat().st_size > self.max_audio_bytes:
                    raise FishAudioError("reference audio exceeds the audio safety limit", code="reference_audio_too_large", retryable=False)
            except OSError as exc:
                raise FishAudioError(f"reference audio cannot be read: {reference_audio}", code="reference_audio_unavailable", retryable=False) from exc
            try:
                encoded = base64.b64encode(reference_audio.read_bytes()).decode("ascii")
            except OSError as exc:
                raise FishAudioError(f"reference audio cannot be read: {reference_audio}", code="reference_audio_unavailable", retryable=False) from exc
            # This is request transport only. Generated results are always
            # persisted as files and never returned as base64.
            payload["reference_audio"] = encoded
            payload["reference_audio_mime"] = mimetypes.guess_type(reference_audio.name)[0] or "audio/wav"
            payload["references"] = [{"audio": encoded, "text": reference_text}]
        if provider_options:
            if not isinstance(provider_options, dict):
                raise FishAudioError("provider_options.fish_audio must be an object", code="invalid_provider_options", retryable=False)
            reserved = {"text", "format", "stream", "language", "style", "reference_id", "reference_audio", "reference_text"}
            if reserved.intersection(provider_options):
                raise FishAudioError("provider_options.fish_audio cannot override generic speech fields", code="invalid_provider_options", retryable=False)
            payload.update(provider_options)
        status, headers, raw = self._request("/v1/tts", method="POST", payload=payload, timeout=timeout)
        if status != 200 or not raw:
            raise FishAudioError(f"Fish Audio returned an empty response (HTTP {status})", code="fish_audio_empty_audio", retryable=False)
        content_type = (headers.get_content_type() or "").lower()
        metadata: dict = {"content_type": content_type, "stream": bool(stream)}
        mpeg_frame = len(raw) >= 2 and raw[0] == 0xFF and (raw[1] & 0xE0) == 0xE0
        if content_type.startswith("audio/") or raw.startswith((b"RIFF", b"ID3", b"OggS", b"fLaC")) or mpeg_frame:
            detected_mime = "audio/wav" if raw.startswith(b"RIFF") else "audio/mpeg" if raw.startswith(b"ID3") or mpeg_frame else "audio/ogg" if raw.startswith(b"OggS") else "audio/flac" if raw.startswith(b"fLaC") else None
            return raw, content_type or detected_mime or f"audio/{output_format}", metadata
        try:
            value = json.loads(raw)
        except ValueError as exc:
            raise FishAudioError("Fish Audio response is neither audio bytes nor JSON", code="fish_audio_protocol_error", retryable=False) from exc
        if not isinstance(value, dict):
            raise FishAudioError("Fish Audio JSON response must be an object", code="fish_audio_protocol_error", retryable=False)
        encoded = value.get("audio") or value.get("audio_base64") or value.get("data")
        if not isinstance(encoded, str):
            raise FishAudioError("Fish Audio JSON response has no audio payload", code="fish_audio_protocol_error", retryable=False)
        try:
            audio = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError) as exc:
            raise FishAudioError("Fish Audio returned malformed audio data", code="fish_audio_protocol_error", retryable=False) from exc
        if not audio:
            raise FishAudioError("Fish Audio returned empty audio data", code="fish_audio_empty_audio", retryable=False)
        metadata.update({key: value[key] for key in ("duration_ms", "sample_rate") if key in value})
        json_mpeg = len(audio) >= 2 and audio[0] == 0xFF and (audio[1] & 0xE0) == 0xE0
        detected_mime = "audio/wav" if audio.startswith(b"RIFF") else "audio/mpeg" if audio.startswith(b"ID3") or json_mpeg else "audio/ogg" if audio.startswith(b"OggS") else "audio/flac" if audio.startswith(b"fLaC") else None
        response_mime = str(value.get("mime") or (content_type if content_type.startswith("audio/") else "") or detected_mime or f"audio/{output_format}")
        if not response_mime.startswith("audio/"):
            raise FishAudioError("Fish Audio JSON response has a non-audio MIME type", code="fish_audio_protocol_error", retryable=False)
        return audio, response_mime, metadata

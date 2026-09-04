"""Typed, safe FFmpeg/FFprobe operations for deterministic media handling."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
from typing import Any


class MediaError(ValueError):
    """Raised when a media operation cannot be validated or executed."""

    code = "media_error"


def _executable(name: str) -> str:
    value = shutil.which(name)
    if not value:
        error = MediaError(f"{name} is not installed; install FFmpeg to use media capabilities")
        error.code = "dependency_missing"
        raise error
    return value


def _run(command: list[str], timeout: float = 300) -> subprocess.CompletedProcess[str]:
    if not command or any(not isinstance(item, str) for item in command):
        raise MediaError("media command must be a non-empty string argument vector")
    kwargs: dict[str, Any] = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "text": True}
    if os.name == "posix":
        kwargs["start_new_session"] = True
    process = subprocess.Popen(command, **kwargs)
    try:
        stdout, stderr = process.communicate(timeout=max(0.1, float(timeout)))
    except subprocess.TimeoutExpired as exc:
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
            process.wait(timeout=0.5)
        except (OSError, subprocess.TimeoutExpired):
            try:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            except OSError:
                pass
        process.communicate()
        error = MediaError(f"media command timed out after {timeout}s")
        error.code = "provider_timeout"
        raise error from exc
    completed = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    if completed.returncode:
        detail = (completed.stderr or completed.stdout or "media command failed").strip()[-1000:]
        error = MediaError(detail)
        error.code = "media_command_failed"
        raise error
    return completed


def _path(value: Any, field: str) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not str(value).strip():
        raise MediaError(f"{field} must be a file path")
    path = Path(value).expanduser()
    if not path.is_file():
        error = MediaError(f"input file does not exist: {path}")
        error.code = "input_not_found"
        raise error
    return path


def _output(root: Path, stem: str, suffix: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{stem}-{os.urandom(8).hex()}{suffix}"


def _time(value: Any, field: str, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < minimum:
        raise MediaError(f"{field} must be a number >= {minimum}")
    return float(value)


def probe(input_path: Any) -> dict[str, Any]:
    path = _path(input_path, "input")
    output = _run([_executable("ffprobe"), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)], timeout=60)
    try:
        payload = json.loads(output.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise MediaError("ffprobe returned invalid JSON") from exc
    streams = payload.get("streams") if isinstance(payload, dict) else []
    streams = streams if isinstance(streams, list) else []
    video = next((item for item in streams if isinstance(item, dict) and item.get("codec_type") == "video"), None)
    audio = next((item for item in streams if isinstance(item, dict) and item.get("codec_type") == "audio"), None)
    fmt = payload.get("format") if isinstance(payload, dict) else {}
    duration = _float_or_none((fmt or {}).get("duration"))
    result: dict[str, Any] = {"container": (fmt or {}).get("format_name"), "duration": duration, "video": None, "audio": None, "deterministic": True}
    if video:
        result["video"] = {"codec": video.get("codec_name"), "width": video.get("width"), "height": video.get("height"), "fps": _rate(video.get("avg_frame_rate") or video.get("r_frame_rate"))}
    if audio:
        result["audio"] = {"codec": audio.get("codec_name"), "sample_rate": _int_or_none(audio.get("sample_rate")), "channels": audio.get("channels")}
    return result


def _float_or_none(value: Any) -> float | None:
    try:
        result = float(value)
        return result if result >= 0 else None
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    try:
        result = int(value)
        return result if result >= 0 else None
    except (TypeError, ValueError):
        return None


def _rate(value: Any) -> float | None:
    if not isinstance(value, str) or "/" not in value:
        return _float_or_none(value)
    numerator, denominator = value.split("/", 1)
    try:
        return round(float(numerator) / float(denominator), 6) if float(denominator) else None
    except ValueError:
        return None


def extract_frames(input_path: Any, output_root: Path, *, fps: Any = None, timestamps: Any = None, timeout: float = 300) -> dict[str, Any]:
    path = _path(input_path, "input")
    if fps is None and timestamps is None:
        fps = 1.0
    if fps is not None:
        fps = _time(fps, "fps")
        if fps <= 0 or fps > 120:
            raise MediaError("fps must be between 0 and 120")
    if timestamps is not None:
        if not isinstance(timestamps, (list, tuple)) or len(timestamps) > 1000:
            raise MediaError("timestamps must be an array with at most 1000 entries")
        timestamps = sorted({_time(value, "timestamp") for value in timestamps})
    folder = output_root / f"frames-{path.stem}-{os.urandom(6).hex()}"
    folder.mkdir(parents=True, exist_ok=True)
    files: list[str] = []
    if timestamps is not None:
        for index, timestamp in enumerate(timestamps):
            destination = folder / f"frame-{index:06d}.png"
            _run([_executable("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{timestamp:.6f}", "-i", str(path), "-frames:v", "1", str(destination)], timeout=timeout)
            files.append(str(destination))
    else:
        pattern = folder / "frame-%06d.png"
        _run([_executable("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-i", str(path), "-vf", f"fps={fps:.6f}", str(pattern)], timeout=timeout)
        files = [str(item) for item in sorted(folder.glob("frame-*.png"))]
    return {"frames": files, "fps": fps, "timestamps": timestamps, "count": len(files), "deterministic": True}


def _run_to_file(input_path: Any, output_root: Path, suffix: str, args: list[str], timeout: float = 900) -> Path:
    path = _path(input_path, "input")
    destination = _output(output_root, path.stem, suffix)
    _run([_executable("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", *args, str(destination)], timeout=timeout)
    return destination


def extract_audio(input_path: Any, output_root: Path, timeout: float = 900) -> dict[str, Any]:
    destination = _run_to_file(input_path, output_root, ".wav", ["-i", str(_path(input_path, "input")), "-vn", "-acodec", "pcm_s16le", "-ar", "48000", "-ac", "1"], timeout)
    return {"audio_path": str(destination), "mime": "audio/wav", "deterministic": True}


def trim_video(input_path: Any, output_root: Path, start: Any, end: Any, timeout: float = 900) -> dict[str, Any]:
    start_value = _time(start, "start")
    end_value = _time(end, "end")
    if end_value <= start_value:
        raise MediaError("end must be greater than start")
    source = _path(input_path, "input")
    destination = _output(output_root, source.stem, ".mp4")
    _run([_executable("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-ss", str(start_value), "-to", str(end_value), "-i", str(source), "-c", "copy", str(destination)], timeout=timeout)
    return {"media_path": str(destination), "start": start_value, "end": end_value, "deterministic": True}


def transcode(input_path: Any, output_root: Path, *, format: str = "mp4", video_codec: str | None = None, audio_codec: str | None = None, timeout: float = 900) -> dict[str, Any]:
    allowed = {"mp4": ".mp4", "webm": ".webm", "mov": ".mov", "mkv": ".mkv", "wav": ".wav", "flac": ".flac", "mp3": ".mp3"}
    normalized = str(format).lower().lstrip(".")
    if normalized not in allowed:
        raise MediaError(f"format must be one of {sorted(allowed)}")
    source = _path(input_path, "input")
    args = ["-i", str(source)]
    codecs = {"h264": "libx264", "vp9": "libvpx-vp9", "aac": "aac", "opus": "libopus", "mp3": "libmp3lame", "copy": "copy"}
    if video_codec is not None:
        if video_codec not in codecs:
            raise MediaError("unsupported video codec")
        args.extend(["-c:v", codecs[video_codec]])
    if audio_codec is not None:
        if audio_codec not in codecs:
            raise MediaError("unsupported audio codec")
        args.extend(["-c:a", codecs[audio_codec]])
    destination = _output(output_root, source.stem, allowed[normalized])
    _run([_executable("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", *args, str(destination)], timeout=timeout)
    return {"media_path": str(destination), "format": normalized, "deterministic": True}


def concat(inputs: Any, output_root: Path, timeout: float = 900) -> dict[str, Any]:
    if not isinstance(inputs, (list, tuple)) or not inputs or len(inputs) > 100:
        raise MediaError("inputs must contain between 1 and 100 files")
    paths = [_path(item, f"inputs[{index}]") for index, item in enumerate(inputs)]
    list_file = output_root / f"concat-{os.urandom(6).hex()}.txt"
    list_file.parent.mkdir(parents=True, exist_ok=True)
    list_file.write_text("".join(f"file '{str(path).replace(chr(39), chr(39) + chr(39))}'\n" for path in paths), encoding="utf-8")
    destination = _output(output_root, paths[0].stem, ".mp4")
    try:
        _run([_executable("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(destination)], timeout=timeout)
    finally:
        list_file.unlink(missing_ok=True)
    return {"media_path": str(destination), "inputs": [str(path) for path in paths], "deterministic": True}


def audio_transform(input_path: Any, output_root: Path, operation: str, *, sample_rate: Any = None, channels: Any = None, format: str = "wav", timeout: float = 900) -> dict[str, Any]:
    source = _path(input_path, "input")
    args = ["-i", str(source), "-vn"]
    if operation == "resample":
        rate = int(_time(sample_rate, "sample_rate"))
        if rate < 8000 or rate > 192000:
            raise MediaError("sample_rate must be between 8000 and 192000")
        args.extend(["-ar", str(rate)])
    if operation in {"convert", "normalize"}:
        if channels is not None:
            channel_count = int(_time(channels, "channels"))
            if channel_count not in {1, 2}:
                raise MediaError("channels must be 1 or 2")
            args.extend(["-ac", str(channel_count)])
        if operation == "normalize":
            args.extend(["-af", "loudnorm=I=-16:TP=-1.5:LRA=11"])
    formats = {"wav": (".wav", ["-c:a", "pcm_s16le"]), "flac": (".flac", ["-c:a", "flac"]), "mp3": (".mp3", ["-c:a", "libmp3lame"]), "ogg": (".ogg", ["-c:a", "libopus"])}
    normalized = format.lower().lstrip(".")
    if normalized not in formats:
        raise MediaError(f"format must be one of {sorted(formats)}")
    suffix, codec = formats[normalized]
    destination = _output(output_root, source.stem, suffix)
    _run([_executable("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", *args, *codec, str(destination)], timeout=timeout)
    return {"audio_path": str(destination), "mime": f"audio/{normalized}", "format": normalized, "deterministic": True}

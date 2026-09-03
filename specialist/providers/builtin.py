"""Dependency-free fallback providers.

These providers make the runtime useful immediately (including in CI and on a
fresh machine) while exposing a stable contract for real YOLO/SAM/PaddleOCR/
MinerU/whisper providers to be added later. They inspect lightweight media
metadata and return valid, explicit results instead of pretending a model ran.
"""

from __future__ import annotations

import struct
import wave
import zlib
from pathlib import Path
from typing import Any


def image_dimensions(path: Path) -> tuple[int, int] | None:
    try:
        with path.open("rb") as stream:
            head = stream.read(32)
            if head.startswith(b"\x89PNG\r\n\x1a\n") and len(head) >= 24:
                return struct.unpack(">II", head[16:24])
            if head[:3] == b"GIF" and len(head) >= 10:
                return struct.unpack("<HH", head[6:10])
            if head[:2] == b"BM" and len(head) >= 26:
                return struct.unpack("<II", head[18:26])
            if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
                with path.open("rb") as full:
                    full.seek(12)
                    chunk_header = full.read(8)
                    if chunk_header[:4] == b"VP8X":
                        chunk = full.read(10)
                        if len(chunk) >= 10:
                            return (1 + int.from_bytes(chunk[4:7], "little"), 1 + int.from_bytes(chunk[7:10], "little"))
            if head[:2] == b"\xff\xd8":
                with path.open("rb") as jpeg:
                    jpeg.read(2)
                    while True:
                        marker = jpeg.read(2)
                        if len(marker) != 2:
                            break
                        if marker[0] != 0xFF:
                            continue
                        length_bytes = jpeg.read(2)
                        if len(length_bytes) != 2:
                            break
                        length = struct.unpack(">H", length_bytes)[0]
                        if marker[1] in set(range(0xC0, 0xC4)) | set(range(0xC5, 0xC8)) | set(range(0xC9, 0xCC)) | set(range(0xCD, 0xD0)):
                            data = jpeg.read(5)
                            if len(data) == 5:
                                return struct.unpack(">HH", data[1:5])
                        jpeg.seek(max(0, length - 2), 1)
    except OSError:
        return None
    return None


def _png(path: Path, width: int, height: int, pixels: bytes):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + pixels[y * width:(y + 1) * width] for y in range(height))
    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")
    path.write_bytes(data)


class BuiltinProvider:
    name = "builtin"
    capability = ""
    model = "fallback"
    requires_verified_artifact = False
    supported_platforms = ("macos-arm64", "linux-x64", "windows-x64")
    supported_devices = ("cpu", "mps", "cuda")
    memory_requirement_mb = 128
    disk_requirement_mb = 0
    license = "MIT"

    def install(self, cache, spec):
        model = getattr(self, "model", None) or spec.model
        cache.mark_installed(spec.name, spec.provider, model, license_name=spec.license, commercial=getattr(spec, "commercial", None), source_url=getattr(spec, "source_url", None))
        return {"status": "ready", "downloaded": False, "reason": "fallback provider has no model artifact"}

    def doctor(self, hardware):
        return {"status": "ready", "backend": "builtin-fallback", "hardware": hardware}

    def load(self):
        return self

    def unload(self):
        return None

    def infer(self, input_path: Path, options: dict[str, Any], cache):
        raise NotImplementedError

    def _warning(self):
        return [f"Provider '{self.name}' is running in dependency-free fallback mode; install the optional backend for model inference."]


class DetectProvider(BuiltinProvider):
    name, capability, model = "yolo", "vision.detect", "fallback"

    def infer(self, input_path, options, cache):
        dimensions = image_dimensions(input_path)
        result = {"items": [], "image": {"width": dimensions[0], "height": dimensions[1]} if dimensions else None}
        return result, self._warning()


class SegmentProvider(BuiltinProvider):
    name, capability, model = "sam", "vision.segment", "fallback"

    def infer(self, input_path, options, cache):
        dimensions = image_dimensions(input_path)
        result = {"masks": [], "prompt": options.get("prompt"), "image": {"width": dimensions[0], "height": dimensions[1]} if dimensions else None}
        return result, self._warning()


class OCRProvider(BuiltinProvider):
    name, capability, model = "paddleocr", "vision.ocr", "fallback"

    def infer(self, input_path, options, cache):
        blocks = []
        if input_path.suffix.lower() in {".txt", ".md", ".markdown", ".json"}:
            try:
                text = input_path.read_text(encoding="utf-8").strip()
                if text:
                    blocks.append({"text": text, "bbox": [0, 0, 0, 0], "confidence": 1.0})
            except UnicodeDecodeError:
                pass
        return {"blocks": blocks}, self._warning()


class DepthProvider(BuiltinProvider):
    name, capability, model = "depth-anything", "vision.depth", "fallback"

    def infer(self, input_path, options, cache):
        dimensions = image_dimensions(input_path) or (1, 1)
        width, height = dimensions
        width = min(max(width, 1), 512)
        height = min(max(height, 1), 512)
        pixels = bytes(int(255 * (y / max(height - 1, 1))) for y in range(height) for _ in range(width))
        preview = cache.results / f"{cache.input_hash(input_path)[:16]}-depth.png"
        cache.ensure_dirs()
        _png(preview, width, height, pixels)
        return {"width": dimensions[0], "height": dimensions[1], "depth_map": None, "preview": str(preview), "mode": "relative"}, self._warning()


class ScreenProvider(BuiltinProvider):
    name, capability, model = "omniparser", "screen.parse", "fallback"

    def infer(self, input_path, options, cache):
        dimensions = image_dimensions(input_path)
        return {"elements": [], "image": {"width": dimensions[0], "height": dimensions[1]} if dimensions else None}, self._warning()


class DocumentProvider(BuiltinProvider):
    name, capability, model = "mineru", "document.parse", "fallback"

    def infer(self, input_path, options, cache):
        markdown = ""
        if input_path.suffix.lower() in {".txt", ".md", ".markdown"}:
            try:
                markdown = input_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                markdown = ""
        if not markdown:
            markdown = f"# {input_path.stem}\n\nDocument parsing requires the optional MinerU provider."
        return {"markdown": markdown, "pages": 1, "tables": [], "figures": [], "formulas": [], "artifacts_path": str(cache.results)}, self._warning()


class TranscribeProvider(BuiltinProvider):
    name, capability, model = "whisper.cpp", "audio.transcribe", "fallback"

    def infer(self, input_path, options, cache):
        transcript = ""
        if input_path.suffix.lower() in {".txt", ".md", ".json"}:
            try:
                transcript = input_path.read_text(encoding="utf-8").strip()
            except UnicodeDecodeError:
                pass
        return {"text": transcript, "segments": []}, self._warning()


class VADProvider(BuiltinProvider):
    name, capability, model = "silero-vad", "audio.vad", "fallback"

    def infer(self, input_path, options, cache):
        duration = 0.0
        try:
            with wave.open(str(input_path), "rb") as audio:
                duration = audio.getnframes() / float(audio.getframerate() or 1)
        except (OSError, EOFError, wave.Error):
            pass
        return {"segments": [], "duration_seconds": round(duration, 3)}, self._warning()


BUILTIN_PROVIDERS = {
    "vision.detect": DetectProvider(),
    "vision.segment": SegmentProvider(),
    "vision.ocr": OCRProvider(),
    "vision.depth": DepthProvider(),
    "screen.parse": ScreenProvider(),
    "document.parse": DocumentProvider(),
    "audio.transcribe": TranscribeProvider(),
    "audio.vad": VADProvider(),
}

#!/usr/bin/env python3
"""Run the public CLI and build the README capability gallery.

The gallery is deliberately generated from CLI result envelopes.  It never
invents detections or substitutes a placeholder result for a provider error.
Use ``--allow-errors`` only when auditing a machine that does not have every
optional provider installed; the manifest will retain the structured error.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import signal
import subprocess
import sys
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs" / "assets" / "e2e"


def _font(size: int, bold: bool = False):
    candidates = (
        "/System/Library/Fonts/SFNS.ttf" if not bold else "/System/Library/Fonts/SFNS-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )
    for candidate in candidates:
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


FONT = _font(16)
FONT_BOLD = _font(19, True)
FONT_SMALL = _font(13)


def _slug(value: str) -> str:
    return value.replace(".", "-").replace("_", "-")


class Gallery:
    def __init__(self, python: str, home: Path, backend: str, strict: bool, timeout_seconds: float = 180):
        self.python = python
        self.home = home
        self.backend = backend
        self.strict = strict
        self.timeout_seconds = max(0.1, float(timeout_seconds))
        self.records: dict[str, dict[str, Any]] = {}
        ASSETS.mkdir(parents=True, exist_ok=True)

    def run(self, capability: str, command: str, source: Path | str, options: dict[str, Any] | None = None, *, title: str | None = None):
        args = [self.python, "-m", "specialist", "--home", str(self.home), "--backend", self.backend, "--isolate", command]
        run_options = dict(options or {})
        if command == "clone-voice":
            text = run_options.get("text")
            if not isinstance(text, str) or not text.strip():
                raise ValueError("speech.clone_voice requires a non-empty text option")
            args.extend([text, str(source)])
        else:
            args.append(str(source))
        args.append("--json")
        if run_options:
            args.extend(["--options", json.dumps(run_options, separators=(",", ":"))])
        environment = os.environ.copy()
        environment.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
        process = subprocess.Popen(
            args,
            cwd=ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=(os.name == "posix"),
        )
        try:
            stdout, stderr = process.communicate(timeout=self.timeout_seconds)
            envelope = json.loads(stdout)
        except subprocess.TimeoutExpired:
            # Isolated providers can spawn model/runtime children. Terminate
            # the whole process group so their pipes cannot keep this audit
            # blocked after the CLI timeout.
            try:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGTERM)
                else:
                    process.terminate()
                process.wait(timeout=1)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    if os.name == "posix":
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                except OSError:
                    pass
            process.communicate()
            envelope = {"capability": capability, "error": {"code": "provider_timeout", "message": f"gallery CLI command exceeded {self.timeout_seconds:g} seconds", "retryable": False}}
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{capability}: CLI returned non-JSON output\n{stderr[-2000:]}") from exc
        path = ASSETS / f"{_slug(capability)}.json"
        path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        payload = envelope.get("result")
        degraded = isinstance(payload, dict) and payload.get("status") == "degraded"
        record_status = "error" if envelope.get("error") else "degraded" if degraded else "ok"
        input_record = envelope.get("input") if isinstance(envelope.get("input"), dict) else {}
        record = {
            "capability": capability,
            "title": title or capability,
            "json": path.name,
            "status": record_status,
            "provider": envelope.get("provider"),
            "model": envelope.get("model"),
            "input_sha256": input_record.get("sha256"),
        }
        if envelope.get("error"):
            record["error"] = envelope["error"]
            self.records[capability] = record
            if self.strict:
                error = envelope["error"]
                raise RuntimeError(f"{capability}: [{error.get('code')}] {error.get('message')}")
        else:
            self.records[capability] = record
            if degraded:
                record["warning"] = "result is degraded because one or more child providers are unavailable"
                if self.strict:
                    raise RuntimeError(f"{capability}: result is degraded because a child provider is unavailable")
        return envelope

    def artifact_path(self, uri: str) -> Path:
        if not isinstance(uri, str) or not uri.startswith("artifact://"):
            raise ValueError(f"not an artifact URI: {uri!r}")
        digest = uri.removeprefix("artifact://")
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError(f"invalid artifact digest: {digest!r}")
        path = self.home / "artifacts" / digest[:2] / digest[2:4] / digest
        if not path.is_file():
            raise FileNotFoundError(path)
        return path


def _copy_artifact(gallery: Gallery, uri: str, destination: Path):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(gallery.artifact_path(uri), destination)
    return destination


def _artifact_mime(envelope: dict[str, Any], uri: str) -> str:
    for item in envelope.get("artifacts", []):
        if isinstance(item, dict) and item.get("uri") == uri:
            return str(item.get("mime") or "application/octet-stream")
    return "application/octet-stream"


def _artifact_with_source(envelope: dict[str, Any], suffixes: tuple[str, ...]) -> str | None:
    for item in envelope.get("artifacts", []):
        if not isinstance(item, dict):
            continue
        source_name = str((item.get("metadata") or {}).get("source_name") or "").lower()
        if source_name.endswith(suffixes) and isinstance(item.get("uri"), str):
            return item["uri"]
    return None


def _fit_image(source: Image.Image, size: tuple[int, int]) -> Image.Image:
    image = source.convert("RGB")
    image.thumbnail(size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", size, "#edf3f5")
    canvas.paste(image, ((size[0] - image.width) // 2, (size[1] - image.height) // 2))
    return canvas


def _tile(image: Image.Image, title: str, subtitle: str = "") -> Image.Image:
    width, height = 360, 286
    canvas = Image.new("RGB", (width, height), "#ffffff")
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((0, 0, width - 1, height - 1), radius=8, outline="#c8d6da", width=2)
    draw.text((16, 12), title, fill="#15364a", font=FONT_BOLD)
    if subtitle:
        draw.text((16, 39), subtitle[:52], fill="#54707a", font=FONT_SMALL)
    preview = _fit_image(image, (328, 218))
    canvas.paste(preview, (16, 60))
    return canvas


def _annotated_image(source: Path, result: dict[str, Any], kind: str) -> Image.Image:
    image = Image.open(source).convert("RGB")
    draw = ImageDraw.Draw(image, "RGBA")
    if kind == "detect":
        colors = {"bus": (18, 184, 134, 210), "person": (255, 130, 64, 220)}
        for item in result.get("items", []):
            box = item.get("bbox") or []
            if len(box) != 4:
                continue
            xy = tuple(float(value) for value in box)
            color = colors.get(item.get("label"), (40, 120, 220, 220))
            draw.rectangle(xy, outline=color, width=max(3, image.width // 220))
            label = f"{item.get('label', 'object')} {float(item.get('confidence', 0.0)):.2f}"
            top = max(0, int(xy[1]) - 24)
            draw.rounded_rectangle((xy[0], top, xy[0] + 132, top + 22), radius=4, fill=color)
            draw.text((xy[0] + 5, top + 3), label, fill="white", font=FONT_SMALL)
    elif kind == "ocr":
        for block in result.get("blocks", []):
            box = block.get("bbox") or []
            if len(box) != 4:
                continue
            xy = tuple(float(value) for value in box)
            draw.rectangle(xy, outline=(226, 93, 68, 230), width=3)
            draw.text((xy[0], max(0, xy[1] - 18)), str(block.get("text", ""))[:40], fill=(160, 48, 34, 255), font=FONT_SMALL)
    elif kind == "sam":
        for mask in result.get("masks", []):
            polygon = mask.get("polygon") or []
            if len(polygon) < 3:
                continue
            points = [(float(item[0]), float(item[1])) for item in polygon if len(item) >= 2]
            draw.polygon(points, fill=(25, 185, 167, 70), outline=(8, 128, 120, 240))
    elif kind in {"pose", "face", "hands"}:
        colors = {"pose": (239, 126, 34, 235), "face": (60, 127, 210, 220), "hands": (193, 76, 167, 230)}
        for group in result.get({"pose": "persons", "face": "faces", "hands": "hands"}[kind], []):
            points = []
            for landmark in group.get("landmarks", []):
                x = float(landmark.get("x", 0)) * image.width
                y = float(landmark.get("y", 0)) * image.height
                points.append((x, y))
                draw.ellipse((x - 3, y - 3, x + 3, y + 3), fill=colors[kind])
            if kind == "pose":
                for first, second in ((11, 12), (11, 13), (13, 15), (12, 14), (14, 16), (11, 23), (12, 24), (23, 24), (23, 25), (25, 27), (24, 26), (26, 28)):
                    if first < len(points) and second < len(points):
                        draw.line((points[first], points[second]), fill=colors[kind], width=4)
    return image


def _waveform(path: Path, width: int = 328, height: int = 218) -> Image.Image:
    canvas = Image.new("RGB", (width, height), "#f5f8f9")
    draw = ImageDraw.Draw(canvas)
    try:
        try:
            with wave.open(str(path), "rb") as stream:
                frames = stream.readframes(stream.getnframes())
                channels, width_bytes = stream.getnchannels(), stream.getsampwidth()
        except (OSError, EOFError, wave.Error):
            # Decode compressed artifacts only for the visual preview; the
            # original encoded artifact remains the file served by README.
            ffmpeg = shutil.which("ffmpeg")
            if not ffmpeg:
                raise ValueError("ffmpeg is required for compressed waveform previews")
            decoded = subprocess.run(
                [ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(path), "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=30,
            )
            if decoded.returncode:
                raise ValueError((decoded.stderr or b"audio decode failed").decode(errors="replace"))
            frames, channels, width_bytes = decoded.stdout, 1, 2
        if width_bytes != 2:
            raise ValueError("only PCM16 waveform previews are supported")
        values = []
        for index in range(0, len(frames), width_bytes * channels * max(1, len(frames) // (width * 4 * width_bytes * channels))):
            chunk = frames[index:index + width_bytes * channels]
            if len(chunk) < width_bytes:
                break
            values.append(int.from_bytes(chunk[:width_bytes], "little", signed=True) / 32768.0)
        if not values:
            values = [0.0]
        step = max(1, len(values) // width)
        points = []
        for x in range(width):
            sample = values[min(len(values) - 1, x * step)]
            points.append((x, height / 2 - sample * (height * 0.4)))
        draw.line(points, fill="#0f8f85", width=2)
        draw.line((0, height / 2, width, height / 2), fill="#bed0d4", width=1)
    except (OSError, EOFError, wave.Error, ValueError):
        draw.text((12, height // 2 - 8), "audio artifact", fill="#54707a", font=FONT_SMALL)
    return canvas


def _json_card(value: Any, width: int = 328, height: int = 218) -> Image.Image:
    canvas = Image.new("RGB", (width, height), "#f5f8f9")
    draw = ImageDraw.Draw(canvas)
    lines = json.dumps(value, ensure_ascii=False, indent=2).splitlines()[:11]
    for index, line in enumerate(lines):
        draw.text((10, 8 + index * 18), line[:45], fill="#24434d", font=FONT_SMALL)
    return canvas


def _timeline_card(value: dict[str, Any], width: int = 328, height: int = 218) -> Image.Image:
    canvas = Image.new("RGB", (width, height), "#f5f8f9")
    draw = ImageDraw.Draw(canvas)
    segments = [item for item in value.get("segments", []) if isinstance(item, dict)]
    ends = [float(item.get("end", 0)) for item in segments if isinstance(item.get("end"), (int, float))]
    duration = max(ends or [float(value.get("duration_seconds") or 1.0), 1.0])
    labels = []
    for item in segments:
        label = str(item.get("speaker") or item.get("label") or "speech")
        if label not in labels:
            labels.append(label)
    labels = labels[:6] or ["speech"]
    palette = ("#0f8f85", "#ec713c", "#347bc1", "#b1539d", "#737f2f", "#7457b8")
    left, right = 72, width - 10
    row_height = max(22, min(34, (height - 42) // len(labels)))
    for index, label in enumerate(labels):
        y = 26 + index * row_height
        draw.text((8, y + 4), label[:9], fill="#54707a", font=FONT_SMALL)
        draw.line((left, y + 13, right, y + 13), fill="#c8d6da", width=2)
    for item in segments:
        try:
            start, end = float(item.get("start", 0)), float(item.get("end", 0))
        except (TypeError, ValueError):
            continue
        label = str(item.get("speaker") or item.get("label") or "speech")
        row = labels.index(label) if label in labels else 0
        y = 26 + row * row_height
        x1 = left + (right - left) * max(0.0, min(duration, start)) / duration
        x2 = left + (right - left) * max(0.0, min(duration, end)) / duration
        color = palette[row % len(palette)]
        draw.rounded_rectangle((x1, y + 5, max(x1 + 3, x2), y + 21), radius=3, fill=color)
    draw.text((left, 6), "0s", fill="#54707a", font=FONT_SMALL)
    end_label = f"{duration:.1f}s"
    end_box = draw.textbbox((0, 0), end_label, font=FONT_SMALL)
    draw.text((right - (end_box[2] - end_box[0]), 6), end_label, fill="#54707a", font=FONT_SMALL)
    transcript = " ".join(str(item.get("text") or "").strip() for item in segments if item.get("text")).strip()
    if transcript:
        draw.text((8, height - 24), transcript[:58], fill="#24434d", font=FONT_SMALL)
    return canvas


def _geometry_points(options: dict[str, Any]) -> list[tuple[str, list[tuple[float, float]]]]:
    """Extract the actual image coordinates supplied to a geometry command."""
    groups: list[tuple[str, list[tuple[float, float]]]] = []
    for key in ("a", "vertex", "b", "c", "points", "source", "destination", "image_points", "object_points"):
        value = options.get(key)
        if not isinstance(value, list):
            continue
        if value and isinstance(value[0], (int, float)) and len(value) >= 2:
            value = [value]
        points: list[tuple[float, float]] = []
        for item in value:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                try:
                    points.append((float(item[0]), float(item[1])))
                except (TypeError, ValueError):
                    continue
        if points:
            groups.append((key, points))
    return groups


def _geometry_card(capability: str, value: Any, source: Path | None = None, options: dict[str, Any] | None = None) -> Image.Image:
    """Show geometry measurements in the scene that supplied their coordinates."""
    if source is None:
        canvas = Image.new("RGB", (328, 218), "#f5f8f9")
        draw = ImageDraw.Draw(canvas)
        draw.text((14, 14), capability.rsplit(".", 1)[-1], fill="#15364a", font=FONT_BOLD)
        draw.text((14, 52), json.dumps(value, ensure_ascii=False)[:320], fill="#24434d", font=FONT_SMALL)
        return canvas

    image = Image.open(source).convert("RGB")
    draw = ImageDraw.Draw(image, "RGBA")
    palette = [(15, 143, 133, 235), (239, 126, 50, 235), (47, 121, 205, 235), (193, 76, 167, 235)]
    for group_index, (label, points) in enumerate(_geometry_points(options or {})):
        color = palette[group_index % len(palette)]
        if len(points) >= 3 and label in {"points", "source", "destination", "image_points", "object_points"}:
            draw.line(points + [points[0]], fill=color, width=max(3, image.width // 260), joint="curve")
        elif len(points) >= 2:
            draw.line(points, fill=color, width=max(3, image.width // 260))
        for x, y in points:
            radius = max(5, image.width // 90)
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color, outline="white", width=2)
        if points:
            draw.text((points[0][0] + 8, max(0, points[0][1] - 20)), label, fill="white", font=FONT_SMALL)
    width, height = image.size
    summary = json.dumps(value, ensure_ascii=False, separators=(",", ":"))[:120]
    draw.rectangle((0, max(0, height - 34), width, height), fill=(16, 42, 54, 205))
    draw.text((8, max(0, height - 28)), summary, fill="white", font=FONT_SMALL)
    return _fit_image(image, (328, 218))


def build(args: argparse.Namespace) -> int:
    gallery = Gallery(args.python, Path(args.home).expanduser(), args.backend, not args.allow_errors, args.timeout_seconds)
    city_scene = ASSETS / "bus-input.jpg"
    boats_scene = ASSETS / "boats-input.jpg"
    ocr_input = ASSETS / "ocr-table.png"
    person = ASSETS / "person-input.jpg"
    face_input = ASSETS / "person-input.jpg"
    hand_input = ASSETS / "hand-input.jpg"
    screen_input = ASSETS / "specialist-github-screen.png"
    audio = ASSETS / "meeting-two-speaker.wav"
    noisy_audio = ASSETS / "meeting-two-speaker-noisy.wav"
    clone_reference = ASSETS / "audio-source.wav"
    video = ASSETS / "video-input.mp4"
    tiles: list[Image.Image] = []
    audio_files: dict[str, str] = {}

    # Reference perception outputs.
    detect = gallery.run("vision.detect", "detect", city_scene, title="YOLO object detection")
    detect_items = (detect.get("result") or {}).get("items", [])
    tiles.append(_tile(_annotated_image(city_scene, detect["result"], "detect"), "Curbside safety · YOLO", f"{len(detect_items)} vehicles and pedestrians"))
    city_width, city_height = Image.open(city_scene).size

    def _center(item: dict[str, Any]) -> tuple[float, float] | None:
        box = item.get("bbox") or []
        if len(box) != 4:
            return None
        try:
            return ((float(box[0]) + float(box[2])) / 2, (float(box[1]) + float(box[3])) / 2)
        except (TypeError, ValueError):
            return None

    bus_item = next((item for item in detect_items if item.get("label") == "bus"), detect_items[0] if detect_items else {})
    bus_box = bus_item.get("bbox") or [0, 0, city_width, city_height]
    if len(bus_box) != 4:
        bus_box = [0, 0, city_width, city_height]
    bus_corners = [[float(bus_box[0]), float(bus_box[1])], [float(bus_box[2]), float(bus_box[1])], [float(bus_box[2]), float(bus_box[3])], [float(bus_box[0]), float(bus_box[3])]]
    people = [_center(item) for item in detect_items if item.get("label") == "person"]
    people = [point for point in people if point is not None]
    anchor_a = _center(bus_item) or ((bus_corners[0][0] + bus_corners[2][0]) / 2, (bus_corners[0][1] + bus_corners[2][1]) / 2)
    anchor_b = people[0] if people else (bus_corners[0][0], bus_corners[0][1])
    anchor_c = people[1] if len(people) > 1 else (bus_corners[2][0], bus_corners[2][1])
    segment = gallery.run("vision.segment", "segment", city_scene, {"point": [420, 360]}, title="SAM segmentation")
    tiles.append(_tile(_annotated_image(city_scene, segment["result"], "sam"), "Vehicle cutout · SAM", "pixel mask for inspection"))
    ocr = gallery.run("vision.ocr", "ocr", ocr_input, title="PaddleOCR")
    tiles.append(_tile(_annotated_image(ocr_input, ocr["result"], "ocr"), "Operations table · PaddleOCR", f"{len(ocr['result'].get('blocks', []))} text regions"))
    depth = gallery.run("vision.depth", "depth", city_scene, {"mode": "relative"}, title="Depth Anything")
    preview_uri = (depth.get("result") or {}).get("preview")
    if preview_uri:
        depth_path = _copy_artifact(gallery, preview_uri, ASSETS / "depth-preview.png")
        tiles.append(_tile(Image.open(depth_path), "Scene layout · Depth Anything", "relative depth map for navigation"))
    pose = gallery.run("human.pose", "pose", hand_input, title="MediaPipe pose")
    tiles.append(_tile(_annotated_image(hand_input, pose["result"], "pose"), "Motion coaching · MediaPipe pose", "33 full-body landmarks"))
    face = gallery.run("human.face_landmarks", "face-landmarks", face_input, title="MediaPipe face landmarks")
    tiles.append(_tile(_annotated_image(face_input, face["result"], "face"), "Identity surface · face landmarks", "468-point face mesh"))
    hands = gallery.run("human.hand_landmarks", "hand-landmarks", hand_input, title="MediaPipe hand landmarks")
    tiles.append(_tile(_annotated_image(hand_input, hands["result"], "hands"), "Gesture input · hand landmarks", "21-point open-hand tracking"))
    gesture = gallery.run("human.gesture", "gesture", hand_input, title="MediaPipe gesture")
    tiles.append(_tile(_json_card(gesture["result"]), "Gesture input · classifier", "open-hand command signal"))

    # Audio and speech outputs.
    vad = gallery.run("audio.vad", "vad", audio, title="Silero VAD")
    audio_files["audio.vad"] = audio.name
    tiles.append(_tile(_timeline_card(vad["result"]), "Meeting audio · Silero VAD", f"{len(vad['result'].get('segments', []))} speech intervals"))
    transcribe = gallery.run("audio.transcribe", "transcribe", audio, title="whisper.cpp")
    audio_files["audio.transcribe"] = audio.name
    tiles.append(_tile(_waveform(audio), "Meeting notes · whisper.cpp", transcribe["result"].get("text", "")))
    transcript_segments = list((transcribe.get("result") or {}).get("segments") or [])
    denoise = gallery.run("audio.denoise", "denoise", noisy_audio, {"strength": "balanced"}, title="DeepFilterNet")
    denoise_audio = (denoise.get("result") or {}).get("audio", {}).get("artifact")
    if denoise_audio:
        denoise_path = _copy_artifact(gallery, denoise_audio, ASSETS / "audio-denoised-balanced.wav")
        audio_files["audio.denoise"] = denoise_path.name
        tiles.append(_tile(_waveform(denoise_path), "Call cleanup · DeepFilterNet", "balanced profile · processed artifact"))
    # Optional provider-backed capabilities are still invoked through the same
    # CLI. On a machine without their weights, --allow-errors records the
    # structured error in the manifest and leaves the visual grid unchanged.
    optional_runs = [
        ("screen.parse", "parse-screen", screen_input, {"max_elements": 200, "caption_batch_size": 16, "min_confidence": 0.5}),
        ("document.parse", "parse-document", ASSETS / "brief-input.pdf", {"backend": "pipeline", "method": "txt", "formula": True, "table": True}),
        ("speech.diarize", "diarize", audio, {"min_speakers": 2, "max_speakers": 2, "exclusive": True}),
        ("speech.align_transcript", "align-transcript", audio, {"transcript": transcript_segments}),
        ("speech.meeting", "meeting", audio, {"min_speakers": 2, "max_speakers": 2, "exclusive": True}),
        ("vision.embed", "embed", city_scene, {}),
        ("vision.embed_text", "embed-text", city_scene, {"text": "a city bus in a street"}),
        ("vision.similarity", "similarity", city_scene, {"other_input": str(person)}),
        ("vision.search", "search", city_scene, {"query": "street vehicle", "corpus": [str(city_scene), str(person), str(ocr_input)], "top_k": 3}),
        ("vision.find_similar", "find-similar", city_scene, {"corpus": [str(city_scene), str(person), str(ocr_input)], "top_k": 3}),
        ("identity.face.detect", "face-detect", person, {}),
        ("identity.face.embed", "face-embed", person, {}),
        ("identity.face.verify", "face-verify", person, {"other_input": str(person)}),
        ("vision.face_compare", "face-compare", person, {"other_input": str(person)}),
        ("vision.human_state", "human-state", hand_input, {"min_confidence": 0.5}),
        ("vision.measure", "measure", city_scene, {"points": [list(anchor_a), list(anchor_b)]}),
        ("media.transcribe_video", "transcribe-video", video, {}),
    ]
    if not args.skip_optional:
        diarization_segments: list[dict[str, Any]] = []
        for capability, command, source, options in optional_runs:
            if capability == "speech.align_transcript":
                options = {**options, "diarization": diarization_segments}
            result = gallery.run(capability, command, source, options)
            if result.get("error"):
                continue
            payload = result.get("result") or {}
            # A composite can return a well-formed degraded envelope when one
            # of its optional children is unavailable. Keep the audit record,
            # but do not present an empty/degraded response as a product demo.
            if payload.get("status") == "degraded":
                continue
            if capability == "speech.diarize":
                diarization_segments = list(payload.get("segments") or [])
            if capability == "screen.parse":
                preview_uri = payload.get("preview")
                preview = gallery.artifact_path(preview_uri) if isinstance(preview_uri, str) and preview_uri.startswith("artifact://") else Path(str(preview_uri))
                tiles.append(_tile(Image.open(preview), "UI actions · OmniParser", f"{len(payload.get('elements', []))} actionable elements"))
            elif capability == "document.parse":
                document_preview = _artifact_with_source(result, (".jpg", ".png"))
                preview_image = _json_card({"pages": payload.get("pages"), "tables": len(payload.get("tables", [])), "figures": len(payload.get("figures", [])), "formulas": len(payload.get("formulas", []))})
                if document_preview and _artifact_mime(result, document_preview).startswith("image/"):
                    preview_image = Image.open(gallery.artifact_path(document_preview))
                tiles.append(_tile(preview_image, "Document pipeline · MinerU", f"{payload.get('pages')} pages · {len(payload.get('tables', []))} tables · {len(payload.get('formulas', []))} formulas"))
            elif capability in {"speech.align_transcript", "speech.diarize", "speech.meeting"}:
                tiles.append(_tile(_timeline_card(payload), capability, f"{len(payload.get('segments', []))} timeline segments"))
            elif capability in {"vision.embed", "vision.embed_text", "vision.similarity", "vision.search", "vision.find_similar"}:
                tiles.append(_tile(_json_card(payload), capability, "visual retrieval result"))
            elif capability in {"identity.face.detect", "identity.face.embed", "identity.face.verify", "vision.face_compare"}:
                tiles.append(_tile(_json_card(payload), capability, "local identity result"))
            elif capability == "vision.human_state":
                tiles.append(_tile(_json_card(payload), "Human state · composite", "perception signals in one trace"))
            elif capability == "vision.measure":
                tiles.append(_tile(_json_card(payload), "Spatial measurement · composite", "detection + depth + geometry"))
            elif capability == "media.transcribe_video":
                tiles.append(_tile(_waveform(audio), "Video notes · transcribe_video", payload.get("text", "")))

    # Deterministic operators and media.
    geometry_calls = [
        ("vision.geometry.distance", "geometry-distance", {"a": list(anchor_a), "b": list(anchor_b)}),
        ("vision.geometry.angle", "geometry-angle", {"a": list(anchor_a), "vertex": list(anchor_b), "c": list(anchor_c)}),
        ("vision.geometry.area", "geometry-area", {"points": bus_corners}),
        ("vision.geometry.contour", "geometry-contour", {"points": bus_corners, "closed": True}),
        ("vision.geometry.homography", "geometry-homography", {"source": bus_corners, "destination": [[0, 0], [city_width, 0], [city_width, city_height], [0, city_height]]}),
        ("vision.geometry.perspective_transform", "geometry-perspective-transform", {"points": [list(anchor_a)], "matrix": [[1, 0, 12], [0, 1, 8], [0, 0, 1]]}),
        ("vision.geometry.calibrate_camera", "geometry-calibrate-camera", {"image_size": [city_width, city_height], "object_points": [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], "image_points": bus_corners}),
        ("vision.geometry.solve_pnp", "geometry-solve-pnp", {"object_points": [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], "image_points": bus_corners, "camera_matrix": [[900, 0, city_width / 2], [0, 900, city_height / 2], [0, 0, 1]], "distortion": [0, 0, 0, 0, 0]}),
        ("vision.geometry.match_features", "geometry-match-features", {"image_a": str(city_scene), "image_b": str(boats_scene)}),
    ]
    geometry_titles = {
        "vision.geometry.distance": "Vehicle spacing · distance",
        "vision.geometry.angle": "Traffic geometry · angle",
        "vision.geometry.area": "Vehicle footprint · area",
        "vision.geometry.contour": "Vehicle outline · contour",
        "vision.geometry.homography": "Camera alignment · homography",
        "vision.geometry.perspective_transform": "View correction · perspective",
        "vision.geometry.calibrate_camera": "Camera setup · calibration",
        "vision.geometry.solve_pnp": "Pose solve · PnP",
        "vision.geometry.match_features": "Scene registration · features",
    }
    for capability, command, options in geometry_calls:
        result = gallery.run(capability, command, city_scene, options)
        if result.get("error"):
            continue
        tiles.append(_tile(_geometry_card(capability, result["result"], city_scene, options), geometry_titles.get(capability, capability), "scene-linked OpenCV measurement"))
    for capability, command, options in [
        ("vision.transform.crop", "transform-crop", {"x": int(bus_corners[0][0]), "y": int(bus_corners[0][1]), "width": int(bus_corners[1][0] - bus_corners[0][0]), "height": int(bus_corners[2][1] - bus_corners[0][1])}),
        ("vision.transform.resize", "transform-resize", {"width": 960, "height": 640}),
        ("vision.transform.rotate", "transform-rotate", {"degrees": 8}),
        ("vision.transform.warp", "transform-warp", {"matrix": [[1, 0, 18], [0, 1, 12], [0, 0, 1]]}),
        ("vision.transform.colorspace", "transform-colorspace", {"colorspace": "Gray"}),
        ("vision.transform.blur", "transform-blur", {"sigma": 2}),
        ("vision.transform.threshold", "transform-threshold", {"percent": 55}),
    ]:
        result = gallery.run(capability, command, boats_scene if capability != "vision.transform.crop" else city_scene, options)
        if result.get("error"):
            continue
        uri = (result.get("result") or {}).get("image") or (result.get("result") or {}).get("image_path")
        image_path = Path(uri) if isinstance(uri, str) and not uri.startswith("artifact://") else gallery.artifact_path(uri)
        tiles.append(_tile(Image.open(image_path), capability, "publishing and inspection transform"))

    # Media fixture is created once outside the script so the CLI remains the
    # only execution path for every media capability result.
    media_results = [
        ("media.probe", "media-probe", video, {}),
        ("media.video.extract_frames", "extract-frames", video, {"fps": 1}),
        ("media.video.trim", "trim-video", video, {"start": 0, "end": 1}),
        ("media.video.transcode", "transcode-video", video, {"format": "mp4"}),
        ("media.video.concat", "concat-video", video, {"inputs": [str(video), str(video)]}),
        ("media.audio.extract", "extract-audio", video, {}),
        ("media.audio.trim", "trim-audio", audio, {"start": 0, "end": 1}),
        ("media.audio.resample", "resample-audio", audio, {"sample_rate": 8000}),
        ("media.audio.convert", "convert-audio", audio, {"format": "flac"}),
        ("media.audio.normalize", "normalize-audio", audio, {}),
    ]
    for capability, command, source, options in media_results:
        result = gallery.run(capability, command, source, options)
        if result.get("error"):
            continue
        payload = result.get("result") or {}
        output_uri = payload.get("preview") or payload.get("frame") or payload.get("audio") or payload.get("media") or payload.get("audio_path") or payload.get("media_path")
        if isinstance(payload.get("frames"), list) and payload["frames"]:
            output_uri = payload["frames"][0]
        if isinstance(output_uri, dict):
            output_uri = output_uri.get("artifact")
        if isinstance(output_uri, str) and output_uri.startswith("artifact://"):
            output_path = gallery.artifact_path(output_uri)
            # The operation result is authoritative for the encoded format;
            # older artifact metadata may still reflect the source suffix.
            mime = str(payload.get("mime") or _artifact_mime(result, output_uri))
            if mime.startswith("audio/"):
                extension = {"audio/wav": ".wav", "audio/flac": ".flac", "audio/mpeg": ".mp3", "audio/ogg": ".ogg"}.get(mime, ".bin")
                audio_name = f"{_slug(capability)}{extension}"
                destination = _copy_artifact(gallery, output_uri, ASSETS / audio_name)
                audio_files[capability] = destination.name
                tiles.append(_tile(_waveform(destination), "Meeting/media pipeline · " + capability.rsplit(".", 1)[-1], "FFmpeg audio artifact"))
            elif mime.startswith("image/"):
                tiles.append(_tile(Image.open(output_path), "Publishing pipeline · " + capability.rsplit(".", 1)[-1], "FFmpeg image artifact"))
            elif mime.startswith("video/"):
                preview_path = ASSETS / f"{_slug(capability)}-preview.png"
                ffmpeg = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
                command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(output_path), "-frames:v", "1", str(preview_path)]
                subprocess.run(command, check=True, capture_output=True, text=True, timeout=60)
                tiles.append(_tile(Image.open(preview_path), "Publishing pipeline · " + capability.rsplit(".", 1)[-1], "FFmpeg video artifact"))
            else:
                tiles.append(_tile(_json_card(payload), "Publishing pipeline · " + capability.rsplit(".", 1)[-1], "FFmpeg media metadata"))
        else:
            tiles.append(_tile(_json_card(payload), "Publishing pipeline · " + capability.rsplit(".", 1)[-1], "FFmpeg media result"))

    # Run Fish Audio after the other heavyweight providers so its resident
    # model does not compete with vision and document cold starts.
    speak = gallery.run(
        "speech.synthesize",
        "speak",
        "Specialist OS has finished the inspection. All production checks passed.",
        {
            "format": "wav",
            "provider": "fish_audio",
            "style": {"instruction": "calm, precise product voice"},
            "provider_options": {"fish_audio": {"max_new_tokens": 128}},
        },
        title="Fish Audio S2 synthesis",
    )
    speech_audio = (speak.get("result") or {}).get("audio", {}).get("artifact")
    if speech_audio:
        speech_path = _copy_artifact(gallery, speech_audio, ASSETS / "speech-synthesize.wav")
        audio_files["speech.synthesize"] = speech_path.name
        tiles.append(_tile(_waveform(speech_path), "Product voice · Fish Audio S2", "expressive speech artifact"))
    clone = gallery.run(
        "speech.clone_voice",
        "clone-voice",
        clone_reference,
        {
            "text": "The specialist pipeline is ready for the next scene.",
            "reference_text": "And so, my fellow Americans, ask not what your country can do for you, ask what you can do for your country.",
            "format": "wav",
            "provider": "fish_audio",
            "provider_options": {"fish_audio": {"max_new_tokens": 128}},
        },
        title="Fish Audio S2 voice cloning",
    )
    clone_audio = (clone.get("result") or {}).get("audio", {}).get("artifact")
    if clone_audio:
        clone_path = _copy_artifact(gallery, clone_audio, ASSETS / "speech-clone-voice.wav")
        audio_files["speech.clone_voice"] = clone_path.name
        tiles.append(_tile(_waveform(clone_path), "Voice identity · Fish Audio S2", "reference-conditioned speech"))

    # Save a single 4-column contact sheet. Every tile above came from a
    # successful result envelope, not from a synthetic provider response.
    columns = 4
    rows = math.ceil(len(tiles) / columns)
    sheet = Image.new("RGB", (columns * 360, rows * 286), "#e8eff1")
    for index, tile in enumerate(tiles):
        sheet.paste(tile, ((index % columns) * 360, (index // columns) * 286))
    sheet.save(ASSETS / "capability-gallery.png", optimize=True)
    (ASSETS / "capability-gallery.json").write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "generated_by": "scripts/generate_readme_gallery.py",
                "backend": gallery.backend,
                "records": gallery.records,
                "audio": audio_files,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"gallery": str(ASSETS / "capability-gallery.png"), "tiles": len(tiles), "audio": audio_files, "records": gallery.records}, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", default=sys.executable, help="Python interpreter that has the project provider environment")
    parser.add_argument("--home", default=os.environ.get("SPECIALIST_HOME", str(Path.home() / ".specialist")))
    parser.add_argument("--backend", choices=("auto", "real", "fallback"), default="real")
    parser.add_argument("--timeout-seconds", type=float, default=180, help="Per-capability CLI timeout (default: 180)")
    parser.add_argument("--allow-errors", action="store_true", help="Record provider errors instead of stopping; no error tile is presented as a result")
    parser.add_argument("--skip-optional", action="store_true", help="Skip heavyweight provider calls while iterating on deterministic gallery rendering")
    return build(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())

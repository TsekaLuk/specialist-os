"""Provider-independent Music Pack result contracts (ADR-004)."""

from __future__ import annotations

import math
import re
from typing import Any


ARTIFACT_KINDS = frozenset({
    "music/midi", "music/musicxml", "music/score", "music/fingerprint", "music/analysis",
})
STEMS = frozenset({"vocals", "instrumental", "drums", "bass", "guitar", "piano", "other"})
MUSIC_CAPABILITIES = frozenset({
    "music.analyze", "music.separate", "music.fingerprint", "music.compare_recording",
    "music.transcribe_notes", "music.transcribe_vocal", "music.transcribe_multitrack",
    "music.generate", "music.parse_singing", "music.transcribe_full",
})
_ARTIFACT_URI = re.compile(r"artifact://[0-9a-f]{64}\Z")


def music_classification(capability: str) -> dict[str, str]:
    if capability not in MUSIC_CAPABILITIES:
        return {}
    experimental = capability in {"music.transcribe_multitrack", "music.transcribe_vocal",
                                  "music.parse_singing", "music.transcribe_full", "music.generate"}
    return {"maturity": "EXPERIMENTAL" if experimental else "STABLE",
            "execution_class": "heavy_generative" if capability == "music.generate" else "specialist"}


def music_schemas(capability: str) -> tuple[dict, dict]:
    """Discovery schemas share the same owner as Music payload validation."""
    uri = {"type": "string", "pattern": r"^artifact://[0-9a-f]{64}$"}
    note = {"type": "object", "required": ["pitch", "start", "end"], "properties": {
        "pitch": {"type": "integer", "minimum": 0, "maximum": 127},
        "start": {"type": "number", "minimum": 0}, "end": {"type": "number", "exclusiveMinimum": 0},
        "velocity": {"type": ["number", "null"], "minimum": 0, "maximum": 1}}}
    notes = {"type": "array", "items": note}
    options = {"no_cache": {"type": "boolean"}, "local_only": {"type": "boolean"}}
    properties = {}
    required = []
    if capability == "music.analyze":
        options["features"] = {"type": "array", "items": {"type": "string", "enum": ["chroma", "mfcc", "spectral", "onsets", "tuning"]}}
        properties = {"duration": {"type": "number", "minimum": 0}, "bpm": {"type": ["number", "null"]},
                      "key": {"type": ["string", "null"]}, "scale": {"enum": ["major", "minor", None]},
                      "beats": {"type": "array", "items": {"type": "number", "minimum": 0}},
                      "loudness_lufs": {"type": ["number", "null"]}}
        required = ["duration"]
    elif capability == "music.separate":
        options.update({"stems": {"type": "array", "minItems": 1, "uniqueItems": True, "items": {"enum": ["vocals", "instrumental"]}},
                        "profile": {"enum": ["fast", "balanced", "quality"]}})
        properties = {"stems": {"type": "object", "minProperties": 1, "additionalProperties": uri}}
        required = ["stems"]
    elif capability in {"music.transcribe_notes", "music.transcribe_vocal"}:
        properties = {"notes": notes, "midi": uri}
        required = ["notes", "midi"]
    elif capability == "music.transcribe_multitrack":
        options.update({"profile": {"enum": ["balanced"]}, "device": {"enum": ["cpu", "mps", "cuda"]}})
        properties = {"tracks": {"type": "array", "items": {"type": "object", "required": ["instrument", "notes"],
            "properties": {"instrument": {"type": "string"}, "notes": notes, "midi": uri}}}, "midi": uri}
        required = ["tracks", "midi"]
    elif capability == "music.generate":
        options.update({"duration": {"type": "number", "minimum": 10, "maximum": 120},
            "bpm": {"type": "integer", "minimum": 30, "maximum": 300},
            "key": {"type": "string", "pattern": "^[A-G](#|b)? (major|minor)$"},
            "reference_audio": {"type": "string", "description": "Explicit local audio path or artifact URI"},
            "provider_options": {"type": "object", "maxProperties": 0},
            "seed": {"type": "integer", "minimum": 0, "maximum": 2**32-1},
            "lyrics": {"type": "string", "maxLength": 4096}, "instrumental": {"type": "boolean"},
            "device": {"enum": ["cpu", "mps", "cuda"]}})
        properties = {"audio": uri, "duration": {"type": "number", "exclusiveMinimum": 0}}
        required = ["audio", "duration"]
    elif capability == "music.fingerprint":
        properties = {"fingerprint": {"type": "string", "minLength": 1}, "duration": {"type": "number", "minimum": 0}}
        required = ["fingerprint", "duration"]
    elif capability == "music.compare_recording":
        options["other_input"] = {"type": "string", "description": "Explicit path or artifact URI for the second recording"}
        properties = {"match": {"type": "boolean"}, "similarity": {"type": "number", "minimum": 0, "maximum": 1},
                      "threshold": {"type": "number", "minimum": 0, "maximum": 1}, "metric": {"const": "chromaprint"}}
        required = list(properties)
    else:
        options.update({"child_options": {"type": "object"}, "refine_stems": {"type": "boolean"}})
        properties = {"children": {"type": "object"}, "status": {"enum": ["ok", "degraded"]}}
        required = ["children", "status"]
    return ({"type": "object", "required": ["path"], "properties": {
        "path": {"type": "string"}, "options": {"type": "object", "properties": options}}},
        {"type": "object", "required": required, "properties": properties})


def _number(value: Any, field: str, minimum: float | None = None,
            maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{field} must be a finite number")
    if minimum is not None and value < minimum or maximum is not None and value > maximum:
        raise ValueError(f"{field} is outside its allowed range")
    return value


def _artifact(value: Any, field: str) -> None:
    if not isinstance(value, str) or not _ARTIFACT_URI.fullmatch(value):
        raise ValueError(f"{field} must be a content-addressed artifact:// URI")


def _events(value: Any, field: str) -> None:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a note array")
    for index, note in enumerate(value):
        prefix = f"{field}[{index}]"
        if not isinstance(note, dict):
            raise ValueError(f"{prefix} must be an object")
        pitch = note.get("pitch")
        if isinstance(pitch, bool) or not isinstance(pitch, int) or not 0 <= pitch <= 127:
            raise ValueError(f"{prefix}.pitch must be an integer MIDI pitch from 0 to 127")
        start = _number(note.get("start"), f"{prefix}.start", 0)
        end = _number(note.get("end"), f"{prefix}.end", 0)
        if end <= start:
            raise ValueError(f"{prefix}.end must be later than start")
        for key in ("velocity", "confidence"):
            if key in note and note[key] is not None:
                _number(note[key], f"{prefix}.{key}", 0, 1)


def _timeline(value: Any, field: str, duration: float | None = None) -> None:
    if isinstance(value, str):
        _artifact(value, field)
        return
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array or artifact URI")
    previous = -1.0
    for timestamp in value:
        current = _number(timestamp, field, 0, duration)
        if current < previous:
            raise ValueError(f"{field} must be chronological")
        previous = current


def validate_music_result(capability: str, result: dict[str, Any]) -> None:
    """Reject invalid wire payloads; this function never invents musical values."""
    if capability not in MUSIC_CAPABILITIES:
        raise ValueError(f"unknown Music capability: {capability}")
    if not isinstance(result, dict):
        raise ValueError("music result must be an object")
    if "warnings" in result:
        warnings = result["warnings"]
        if not isinstance(warnings, list) or any(
            not isinstance(w, dict) or not isinstance(w.get("code"), str) or not w["code"]
            for w in warnings
        ):
            raise ValueError("music warnings must be objects with nonempty codes")
    if capability == "music.analyze":
        duration = _number(result.get("duration"), "duration", 0)
        for key in ("bpm", "tuning"):
            if key in result and result[key] is not None:
                _number(result[key], key, 0)
        if "loudness_lufs" in result and result["loudness_lufs"] is not None:
            _number(result["loudness_lufs"], "loudness_lufs")
        if "key" in result and result["key"] is not None and result["key"] not in {
            "C", "C#", "Db", "D", "D#", "Eb", "E", "F", "F#", "Gb", "G", "G#", "Ab", "A", "A#", "Bb", "B",
        }:
            raise ValueError("key must be a pitch class or null")
        if "scale" in result and result["scale"] not in {"major", "minor", None}:
            raise ValueError("scale must be major, minor or null")
        for key in ("beats", "onsets"):
            if key in result:
                _timeline(result[key], key, duration)
        for key in ("chroma", "mfcc", "spectral"):
            if key in result:
                _artifact(result[key], key)
    elif capability == "music.separate":
        stems = result.get("stems")
        if not isinstance(stems, dict) or not stems or not stems.keys() <= STEMS:
            raise ValueError("stems must be a nonempty mapping of supported stem names")
        for name, reference in stems.items():
            _artifact(reference, f"stems.{name}")
    elif capability == "music.fingerprint":
        _number(result.get("duration"), "duration", 0)
        if not isinstance(result.get("fingerprint"), str) or not result["fingerprint"]:
            raise ValueError("fingerprint must be a nonempty string")
    elif capability == "music.compare_recording":
        if not isinstance(result.get("match"), bool):
            raise ValueError("match must be boolean")
        _number(result.get("similarity"), "similarity", 0, 1)
        _number(result.get("threshold"), "threshold", 0, 1)
        if result.get("metric") != "chromaprint":
            raise ValueError("recording comparison must identify its chromaprint metric")
    elif capability in {"music.transcribe_notes", "music.transcribe_vocal"}:
        _events(result.get("notes"), "notes")
        _artifact(result.get("midi"), "midi")
    elif capability == "music.transcribe_multitrack":
        tracks = result.get("tracks")
        if not isinstance(tracks, list):
            raise ValueError("tracks must be an array")
        for index, track in enumerate(tracks):
            if not isinstance(track, dict) or not isinstance(track.get("instrument"), str) or not track["instrument"]:
                raise ValueError(f"tracks[{index}] requires an instrument")
            _events(track.get("notes"), f"tracks[{index}].notes")
            if "midi" in track:
                _artifact(track["midi"], f"tracks[{index}].midi")
        _artifact(result.get("midi"), "midi")
        if "musicxml" in result:
            _artifact(result["musicxml"], "musicxml")
    elif capability == "music.generate":
        _artifact(result.get("audio"), "audio")
        if _number(result.get("duration"), "duration", 0) == 0:
            raise ValueError("generated duration must be positive")
    else:
        _composite(capability, result)


def _composite(capability: str, result: dict[str, Any]) -> None:
    from .schemas import validate_envelope

    children = result.get("children")
    required = ({"audio.transcribe", "music.transcribe_vocal", "music.analyze"}
                if capability == "music.parse_singing" else
                {"music.analyze", "music.transcribe_multitrack", "music.separate"})
    if not isinstance(children, dict) or not required <= children.keys():
        raise ValueError("composite must preserve all required child envelopes")
    allowed = required | {"music.transcribe_notes", "music.transcribe_vocal"}
    if capability == "music.parse_singing":
        allowed.add("media.audio.resample")
    if not children.keys() <= allowed:
        raise ValueError("composite contains an unsupported child capability")
    for name, envelope in children.items():
        if not isinstance(envelope, dict) or envelope.get("capability") != name:
            raise ValueError("child envelope capability does not match its key")
        validate_envelope(envelope)
    failed = any(child["error"] is not None or child["result"].get("status") in {"degraded", "unavailable"}
                 for child in children.values())
    expected = "degraded" if failed else "ok"
    if result.get("status") != expected:
        raise ValueError(f"composite status must be {expected}")

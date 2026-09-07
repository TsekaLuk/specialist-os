"""Local Music provider adapters; optional native dependencies are checked lazily."""

from __future__ import annotations

import json
import math
import contextlib
import io
import sys
import shutil
import tempfile
import logging
from pathlib import Path

from .ipc import WorkerError
from .optional import OptionalProvider, _run_external
from .optional_expansion import ExpansionOptionalProvider, _resolve_file
from ..artifacts import ArtifactStore


class AudioSeparatorProvider(ExpansionOptionalProvider):
    requires_verified_artifact = True
    supported_devices = ("cpu",)
    license = "MIT runtime; UVR checkpoint terms must be reviewed separately"
    MODEL_FILE = "UVR-MDX-NET-Inst_HQ_3.onnx"
    MODEL_KEY = "55657dd70583b0fedfba5f67df11d711"
    PROFILES = {"fast": (.1, False), "balanced": (.25, False), "quality": (.5, True)}

    def __init__(self):
        super().__init__("audio_separator", "music.separate", "uvr-mdx-inst-hq3")

    def _check_dependency(self):
        for module in ("audio_separator", "onnxruntime", "soundfile"):
            self._missing_dependency(module)

    def _load_model(self):
        self._check_dependency()
        # ModelManager already validates both the checkpoint and companion data.
        self._parameters = json.loads((self.artifact_root() / "mdx-model-data.json").read_text())[self.MODEL_KEY]

    def infer(self, input_path, options, cache):
        stems = options.get("stems", ["vocals", "instrumental"])
        profile = options.get("profile", "balanced")
        if (not isinstance(stems, list) or not stems or
                any(not isinstance(s, str) or s not in {"vocals", "instrumental"} for s in stems) or
                len(set(stems)) != len(stems)):
            raise WorkerError("This checkpoint supports vocals and instrumental stems",
                              code="invalid_options", retryable=False)
        if not isinstance(profile, str) or profile not in self.PROFILES:
            raise WorkerError("profile must be fast, balanced, or quality", code="invalid_options", retryable=False)
        if options.get("device", "cpu") != "cpu":
            raise WorkerError("This pinned ONNX separator uses CPU", code="invalid_options", retryable=False)
        self.load()
        import soundfile as sf
        import torch
        from audio_separator.separator import Separator

        info = sf.info(str(input_path))
        if not 0 < info.duration <= 1800 or info.channels not in {1, 2}:
            raise WorkerError("Separation requires mono/stereo audio up to 30 minutes",
                              code="invalid_input", retryable=False)
        model_path = self.artifact_path()
        parameters = self._parameters

        class LocalSeparator(Separator):
            def download_model_files(self, filename):
                if filename != model_path.name:
                    raise ValueError("unexpected separator checkpoint")
                return filename, "MDX", "UVR MDX Inst HQ 3", str(model_path), None

            def load_model_data_using_hash(self, path):
                if Path(path) != model_path:
                    raise ValueError("unexpected separator model path")
                return dict(parameters)

        overlap, denoise = self.PROFILES[profile]
        with tempfile.TemporaryDirectory(prefix="music-separate-") as directory:
            with contextlib.redirect_stdout(sys.stderr):
                separator = LocalSeparator(
                    model_file_dir=str(model_path.parent), output_dir=directory,
                    output_format="WAV", use_soundfile=False, log_level=logging.WARNING,
                    mdx_params={"hop_length": 1024, "segment_size": 256,
                                "overlap": overlap, "batch_size": 1, "enable_denoise": denoise},
                )
                separator.torch_device = torch.device("cpu")
                separator.torch_device_mps = None
                separator.onnx_execution_provider = ["CPUExecutionProvider"]
                separator.load_model(model_path.name)
                outputs = separator.separate(str(input_path), custom_output_names={
                    "Vocals": "vocals", "Instrumental": "instrumental",
                })
            store = ArtifactStore(cache.artifacts)
            references, result = [], {}
            for stem in stems:
                path = Path(directory) / f"{stem}.wav"
                if not path.is_file() or path.name not in {Path(p).name for p in outputs}:
                    raise WorkerError("Separator did not produce the requested stem", code="invalid_provider_result", retryable=False)
                stem_info = sf.info(str(path))
                if abs(stem_info.duration - info.duration) > .1:
                    raise WorkerError("Stem duration differs from input", code="invalid_provider_result", retryable=False)
                ref = store.put_bytes(path.read_bytes(), mime="audio/wav", metadata={"stem": stem})
                references.append(ref.to_dict())
                result[stem] = ref.uri
        return {"stems": result, "duration": info.duration, "profile": profile, "artifacts": references}, []


class MuScriptorProvider(ExpansionOptionalProvider):
    requires_verified_artifact = True
    supported_devices = ("cpu", "mps", "cuda")
    license = "CC-BY-NC-4.0 with supplemental model terms"

    def __init__(self):
        super().__init__("muscriptor", "music.transcribe_multitrack", "muscriptor-medium-f3223696")

    def _check_dependency(self):
        for module in ("muscriptor", "pretty_midi", "soundfile"):
            self._missing_dependency(module)

    def _load_model(self):
        self._check_dependency()
        from muscriptor.transcription_model import TranscriptionModel

        with contextlib.redirect_stdout(sys.stderr):
            self._model = TranscriptionModel.load_model(
                weights_path=self.artifact_path(), device=self._device,
            )

    def infer(self, input_path, options, cache):
        if options.get("profile", "balanced") != "balanced":
            raise WorkerError("The installed medium checkpoint supports profile=balanced",
                              code="invalid_options", retryable=False)
        self._check_dependency()
        import soundfile as sf
        import torch
        import pretty_midi

        device = options.get("device", "cpu")
        if device not in self.supported_devices:
            raise WorkerError("device must be cpu, mps, or cuda", code="invalid_options", retryable=False)
        if getattr(self, "_device", device) != device:
            self.unload()
        self._device = device
        info = sf.info(str(input_path))
        if not 0 < info.duration <= 600 or info.channels not in {1, 2}:
            raise WorkerError("Multitrack transcription requires mono/stereo audio up to 10 minutes",
                              code="invalid_input", retryable=False)
        self.load()
        samples, rate = sf.read(str(input_path), dtype="float32", always_2d=True)
        audio = torch.from_numpy(samples.T.copy())
        # Disable upstream tempo-model downloads. MIDI preserves event seconds;
        # estimated beat grids are a separate music.analyze composition.
        with contextlib.redirect_stdout(sys.stderr), torch.inference_mode():
            data = self._model.transcribe_to_midi(
                (audio, rate), use_sampling=False, beam_size=1, batch_size=1,
                prelude_forcing=True, detect_tempo=False,
            )
        midi = pretty_midi.PrettyMIDI(io.BytesIO(data))
        store = ArtifactStore(cache.artifacts)
        full = store.put_bytes(data, mime="audio/midi",
                               metadata={"kind": "music/midi", "capability": self.capability})
        references = [full.to_dict()]
        tracks = []
        for index, instrument in enumerate(midi.instruments):
            notes = [{"pitch": int(n.pitch), "start": float(n.start), "end": float(n.end),
                      "velocity": float(n.velocity) / 127.0} for n in instrument.notes]
            notes.sort(key=lambda n: (n["start"], n["pitch"], n["end"]))
            single = pretty_midi.PrettyMIDI()
            single.instruments.append(instrument)
            buffer = io.BytesIO()
            single.write(buffer)
            ref = store.put_bytes(buffer.getvalue(), mime="audio/midi",
                                  metadata={"kind": "music/midi", "track": index})
            references.append(ref.to_dict())
            tracks.append({"instrument": instrument.name or (
                "drums" if instrument.is_drum else pretty_midi.program_to_instrument_name(instrument.program)),
                "program": int(instrument.program), "is_drum": bool(instrument.is_drum),
                "notes": notes, "midi": ref.uri})
        return {"tracks": tracks, "midi": full.uri, "duration": info.duration,
                "artifacts": references, "warnings": [
                    {"code": "EXPERIMENTAL_INSTRUMENT_ATTRIBUTION"},
                    {"code": "SCORE_NOT_QUANTIZED", "message": "MIDI preserves event timing; tempo is not estimated."},
                ]}, []


class BasicPitchProvider(ExpansionOptionalProvider):
    requires_verified_artifact = True
    supported_devices = ("cpu",)
    license = "Apache-2.0"

    def __init__(self):
        super().__init__("basic_pitch", "music.transcribe_notes", "basic-pitch-icassp-2022-onnx")

    def _check_dependency(self):
        for module in ("basic_pitch", "onnxruntime", "pretty_midi"):
            self._missing_dependency(module)

    def _load_model(self):
        self._check_dependency()
        from basic_pitch.inference import Model

        self._model = Model(self.artifact_path())

    def infer(self, input_path, options, cache):
        for key in ("onset_threshold", "frame_threshold"):
            value = options.get(key, .5 if key == "onset_threshold" else .3)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
                raise WorkerError(f"{key} must be between 0 and 1", code="invalid_options", retryable=False)
        self.load()
        from basic_pitch.inference import predict

        with contextlib.redirect_stdout(sys.stderr):
            _, midi, events = predict(str(input_path), self._model,
                                     onset_threshold=options.get("onset_threshold", .5),
                                     frame_threshold=options.get("frame_threshold", .3))
        notes = [{"start": float(event[0]), "end": float(event[1]), "pitch": int(event[2]),
                  "velocity": float(event[3])} for event in events]
        notes.sort(key=lambda note: (note["start"], note["pitch"], note["end"]))
        buffer = io.BytesIO()
        midi.write(buffer)
        reference = ArtifactStore(cache.artifacts).put_bytes(buffer.getvalue(), mime="audio/midi",
            metadata={"kind": "music/midi", "capability": self.capability})
        return {"notes": notes, "midi": reference.uri, "artifacts": [reference.to_dict()]}, []


class EssentiaProvider(ExpansionOptionalProvider):
    supported_devices = ("cpu",)
    license = "AGPL-3.0; commercial licensing available from MTG"
    FEATURES = frozenset({"duration", "bpm", "beats", "key", "scale", "loudness_lufs",
                          "onsets", "tuning", "chroma", "mfcc", "spectral"})
    DEFAULT_FEATURES = ("bpm", "beats", "key", "scale", "loudness_lufs")

    def __init__(self):
        super().__init__("essentia", "music.analyze", "essentia-2.1b6.dev1389")

    def _check_dependency(self):
        self._missing_dependency("essentia")

    def infer(self, input_path, options, cache):
        features = options.get("features")
        if features is None:
            features = list(self.DEFAULT_FEATURES)
        if not isinstance(features, list) or not features or any(not isinstance(x, str) or x not in self.FEATURES for x in features):
            raise WorkerError(f"features must be a nonempty list from {sorted(self.FEATURES)}", code="invalid_options", retryable=False)
        self._check_dependency()
        import essentia.standard as es
        import numpy as np

        # Standard MIR algorithms below expect 44.1 kHz. Keep stereo samples
        # for EBU R128; downmix only the tonal/rhythm analysis signal.
        stereo = es.AudioLoader(filename=str(input_path))()[0:3]
        audio, rate, channels = stereo
        if channels not in {1, 2} or not len(audio):
            raise WorkerError("music.analyze requires nonempty mono or stereo audio", code="invalid_input", retryable=False)
        if len(audio) / rate > 1800:
            raise WorkerError("music.analyze currently supports up to 30 minutes", code="input_too_large", retryable=False)
        mono = es.MonoLoader(filename=str(input_path), sampleRate=44100)()
        result = {"duration": len(audio) / float(rate), "warnings": []}
        references = []

        def store_array(name, values):
            ref = ArtifactStore(cache.artifacts).put_bytes(
                json.dumps(values, allow_nan=False, separators=(",", ":")).encode(),
                mime="application/json", metadata={"kind": "music/analysis", "descriptor": name},
            )
            references.append(ref.to_dict())
            return ref.uri

        if "bpm" in features or "beats" in features:
            bpm, beats, confidence, _, intervals = es.RhythmExtractor2013(method="multifeature")(mono)
            if "bpm" in features:
                result["bpm"] = float(bpm) if bpm > 0 else None
            if "beats" in features:
                timestamps = [float(x) for x in beats if 0 <= x <= result["duration"]]
                result["beats"] = store_array("beats", timestamps) if len(timestamps) > 4096 else timestamps
            result["tempo_confidence"] = float(confidence)
            if len(intervals) > 2 and np.mean(intervals) > 0 and np.std(intervals) / np.mean(intervals) > .15:
                result["warnings"].append({"code": "UNSTABLE_TEMPO_TRANSCRIPTION"})
        if "key" in features or "scale" in features:
            key, scale, strength = es.KeyExtractor(sampleRate=44100)(mono)
            result.update({"key": key, "scale": scale, "key_strength": float(strength)})
        if "loudness_lufs" in features:
            _, _, integrated, _ = es.LoudnessEBUR128(sampleRate=float(rate))(audio)
            result["loudness_lufs"] = float(integrated) if math.isfinite(integrated) else None
            if result["loudness_lufs"] is None:
                result["warnings"].append({"code": "LOUDNESS_UNDEFINED"})
        if "onsets" in features:
            onsets, _ = es.OnsetRate()(mono)
            timestamps = [float(x) for x in onsets if 0 <= x <= result["duration"]]
            result["onsets"] = store_array("onsets", timestamps) if len(timestamps) > 4096 else timestamps
        if "tuning" in features:
            frequencies = es.TuningFrequencyExtractor()(mono)
            valid = [float(x) for x in frequencies if math.isfinite(x) and x > 0]
            result["tuning"] = float(np.median(valid)) if valid else None
        descriptors = set(features) & {"chroma", "mfcc", "spectral"}
        if descriptors:
            rows = {key: [] for key in descriptors}
            window, spectrum = es.Windowing(type="hann"), es.Spectrum()
            peaks, hpcp = es.SpectralPeaks(sampleRate=44100), es.HPCP(size=12)
            mfcc = es.MFCC(sampleRate=44100, inputSize=2049)
            centroid = es.Centroid(range=22050)
            for frame in es.FrameGenerator(mono, frameSize=4096, hopSize=2048, startFromZero=True):
                magnitude = spectrum(window(frame))
                if "chroma" in rows:
                    frequencies, amplitudes = peaks(magnitude)
                    rows["chroma"].append(hpcp(frequencies, amplitudes).tolist())
                if "mfcc" in rows:
                    rows["mfcc"].append(mfcc(magnitude)[1].tolist())
                if "spectral" in rows:
                    rows["spectral"].append({"centroid_hz": float(centroid(magnitude))})
            for key, values in rows.items():
                result[key] = store_array(key, {"sample_rate": 44100, "hop_size": 2048, "frames": values})
        result["artifacts"] = references
        return result, []


class ChromaprintProvider(OptionalProvider):
    requires_verified_artifact = False
    supported_devices = ("cpu",)
    memory_requirement_mb = 128
    disk_requirement_mb = 16
    license = "LGPL-2.1-or-later"

    def __init__(self, capability="music.fingerprint"):
        super().__init__("chromaprint", capability, "chromaprint-1.6.1")

    def _check_dependency(self):
        if shutil.which("fpcalc") is None:
            raise WorkerError("Chromaprint fpcalc is required; install chromaprint with your system package manager",
                              code="dependency_missing", retryable=False)
        version = _run_external([shutil.which("fpcalc"), "-version"], timeout=10)
        if version.returncode or not version.stdout.startswith("fpcalc version 1.6.1 "):
            raise WorkerError("This adapter requires Chromaprint fpcalc 1.6.1",
                              code="unsupported_provider_version", retryable=False)

    def _fingerprint(self, path, *, raw=False):
        self._check_dependency()
        command = [shutil.which("fpcalc"), "-json", "-length", "120"]
        if raw:
            command.append("-raw")
        command.append(str(Path(path).resolve()))
        completed = _run_external(command, timeout=180)
        if completed.returncode:
            raise WorkerError(f"Chromaprint failed: {completed.stderr[-1000:]}", code="provider_error", retryable=False)
        try:
            payload = json.loads(completed.stdout)
            fingerprint = payload["fingerprint"]
            duration = float(payload["duration"])
            if not fingerprint or duration <= 0:
                raise ValueError("empty fingerprint or duration")
            if raw and (not isinstance(fingerprint, list) or any(type(x) is not int for x in fingerprint)):
                raise ValueError("raw fingerprint must contain integers")
            if not raw and not isinstance(fingerprint, str):
                raise ValueError("fingerprint must be a string")
        except (ValueError, KeyError, TypeError) as exc:
            raise WorkerError(f"invalid Chromaprint result: {exc}", code="invalid_provider_result", retryable=False) from exc
        return {"duration": duration, "fingerprint": fingerprint}

    def infer(self, input_path, options, cache):
        if self.capability == "music.fingerprint":
            result = self._fingerprint(input_path)
            reference = ArtifactStore(cache.artifacts).put_bytes(
                json.dumps(result, allow_nan=False, sort_keys=True).encode(),
                mime="application/json", metadata={"kind": "music/fingerprint", "capability": self.capability},
            )
            return {**result, "analysis_window_seconds": 120, "artifacts": [reference.to_dict()]}, []
        threshold = options.get("threshold", .9)
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0 <= threshold <= 1:
            raise WorkerError("threshold must be a number between 0 and 1", code="invalid_options", retryable=False)
        other = _resolve_file(options.get("other_input"), cache, "other_input")
        left = self._fingerprint(input_path, raw=True)
        right = self._fingerprint(other, raw=True)
        a, b = left["fingerprint"], right["fingerprint"]
        # Compare aligned recording prefixes, penalizing unmatched subfingerprints.
        # This is deliberately not a time-shift or semantic retrieval engine.
        matching_bits = sum(32 - ((x & 0xffffffff) ^ (y & 0xffffffff)).bit_count() for x, y in zip(a, b))
        similarity = matching_bits / (32 * max(len(a), len(b)))
        return {"match": similarity >= threshold, "similarity": similarity, "threshold": threshold,
                "metric": "chromaprint", "alignment": "recording_start", "analysis_window_seconds": 120,
                "other_input_sha256": cache.input_hash(other)}, []

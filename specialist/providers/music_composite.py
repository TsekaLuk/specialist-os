"""Evidence-preserving music workflows over independent provider calls."""
from .expansion import CompositeProvider, _child_artifacts, _child_provenance, _child_trace, _child_warnings
from .ipc import WorkerError


class MusicCompositeProvider(CompositeProvider):
    def infer(self, input_path, options, cache):
        if self.runtime is None:
            raise WorkerError("Music workflow is not bound to a runtime", code="provider_not_configured", retryable=False)
        required = ("audio.transcribe", "music.transcribe_vocal", "music.analyze") if self.capability == "music.parse_singing" else (
            "music.analyze", "music.transcribe_multitrack", "music.separate")
        allowed = set(required) | {"music.transcribe_notes", "music.transcribe_vocal"}
        child_options = options.get("child_options", {})
        if not isinstance(child_options, dict) or not child_options.keys() <= allowed or any(not isinstance(v, dict) for v in child_options.values()):
            raise WorkerError("child_options must map workflow capabilities to option objects", code="invalid_options", retryable=False)
        refine = options.get("refine_stems", True)
        if not isinstance(refine, bool):
            raise WorkerError("refine_stems must be boolean", code="invalid_options", retryable=False)
        children = {}

        def run(name, source, fixed=None):
            controls = {key: options[key] for key in ("no_cache", "allow_remote", "local_only") if key in options}
            result = self.runtime.run(name, source, {**child_options.get(name, {}), **controls, **(fixed or {})})
            children[name] = result
            return result

        transcript_input = input_path
        if self.capability == "music.parse_singing":
            converted = run("media.audio.resample", input_path, {"sample_rate": 16000, "channels": 1, "format": "wav"})
            if not converted.get("error"):
                transcript_input = converted["result"]["audio_path"]
        for name in required:
            run(name, transcript_input if name == "audio.transcribe" else input_path)
        result = {"children": children}
        if self.capability == "music.parse_singing":
            transcript = children["audio.transcribe"]
            vocal = children["music.transcribe_vocal"]
            if not transcript.get("error") and not vocal.get("error"):
                segments = transcript["result"].get("segments", [])
                # Keep indices into original child results. Overlap is a
                # temporal association, not forced word-to-note alignment.
                result["alignment"] = [{"note_index": index, "segment_indexes": [
                    j for j, segment in enumerate(segments)
                    if max(note["start"], segment["start"]) < min(note["end"], segment["end"])
                ]} for index, note in enumerate(vocal["result"]["notes"])]
                result["alignment_method"] = "interval_overlap"
        elif refine:
            separated = children["music.separate"]
            if not separated.get("error"):
                stems = separated["result"]["stems"]
                for stem, name in (("instrumental", "music.transcribe_notes"), ("vocals", "music.transcribe_vocal")):
                    if stem in stems:
                        run(name, self.runtime.artifacts.resolve(stems[stem]))
        values = list(children.values())
        failed = any(child.get("error") or child.get("result", {}).get("status") in {"degraded", "unavailable"} for child in values)
        result.update({"status": "degraded" if failed else "ok", "_trace": _child_trace(values),
                       "_child_artifacts": _child_artifacts(values), "_child_provenance": _child_provenance(values)})
        return result, _child_warnings(values)

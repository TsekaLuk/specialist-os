"""Public Python SDK for Specialist OS."""

import tempfile
from pathlib import Path

from .runtime import SpecialistRuntime
from .graph import SpecialistGraph
from .cascade import SpecialistCascade
from .node import ComputeNode, NodeScheduler
from .provider_sdk import ProviderAdapter, ProviderResult


class SpeechFacade:
    def __init__(self, specialist):
        self._specialist = specialist

    def synthesize(self, text, *, voice=None, language=None, style=None, format="wav", profile="balanced", provider=None, stream=False, **options):
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text must be a non-empty string")
        temporary = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False)
        try:
            temporary.write(text)
            temporary.close()
            request = {**options, "text": text, "format": format, "profile": profile, "stream": stream}
            if voice is not None:
                request["voice"] = voice
            if language is not None:
                request["language"] = language
            if style is not None:
                request["style"] = style if isinstance(style, dict) else {"instruction": style}
            if provider is not None:
                request["provider"] = provider
            return self._specialist.run("speech.synthesize", temporary.name, request)
        finally:
            Path(temporary.name).unlink(missing_ok=True)

    def clone_voice(self, text, reference_audio, *, reference_text=None, style=None, format="wav", provider="fish_audio", **options):
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text must be a non-empty string")
        reference_value = str(reference_audio)
        reference = reference_value if reference_value.startswith("artifact://") else Path(reference_audio).expanduser()
        request = {**options, "text": text, "reference_audio": str(reference), "format": format, "provider": provider}
        if reference_text is not None:
            request["reference_text"] = reference_text
        if style is not None:
            request["style"] = style if isinstance(style, dict) else {"instruction": style}
        return self._specialist.run("speech.clone_voice", reference, request)


class HumanFacade:
    def __init__(self, specialist):
        self._specialist = specialist

    def pose(self, input_path, **options):
        return self._specialist.run("human.pose", input_path, options)

    def hand_landmarks(self, input_path, **options):
        return self._specialist.run("human.hand_landmarks", input_path, options)

    def face_landmarks(self, input_path, **options):
        return self._specialist.run("human.face_landmarks", input_path, options)

    def gesture(self, input_path, **options):
        return self._specialist.run("human.gesture", input_path, options)


class AudioFacade:
    def __init__(self, specialist):
        self._specialist = specialist

    def denoise(self, input_path, *, strength="balanced", **options):
        return self._specialist.run("audio.denoise", input_path, {**options, "strength": strength})

    def diarize(self, input_path, **options):
        return self._specialist.run("speech.diarize", input_path, options)

    def align_transcript(self, input_path, *, transcript, diarization=None, **options):
        request = {**options, "transcript": transcript}
        if diarization is not None:
            request["diarization"] = diarization
        return self._specialist.run("speech.align_transcript", input_path, request)

    def meeting(self, input_path, **options):
        return self._specialist.run("speech.meeting", input_path, options)


class RetrievalFacade:
    def __init__(self, specialist):
        self._specialist = specialist

    def embed(self, input_path, **options):
        return self._specialist.run("vision.embed", input_path, options)

    def embed_text(self, input_path, text, **options):
        return self._specialist.run("vision.embed_text", input_path, {**options, "text": text})

    def similarity(self, input_path, *, other_input=None, text=None, **options):
        request = {**options}
        if other_input is not None:
            request["other_input"] = str(other_input)
        if text is not None:
            request["text"] = text
        return self._specialist.run("vision.similarity", input_path, request)

    def search(self, input_path, *, corpus, query=None, **options):
        request = {**options, "corpus": corpus}
        if query is not None:
            request["query"] = query
        return self._specialist.run("vision.search", input_path, request)

    def find_similar(self, input_path, *, corpus, query=None, **options):
        request = {**options, "corpus": corpus}
        if query is not None:
            request["query"] = query
        return self._specialist.run("vision.find_similar", input_path, request)


class IdentityFacade:
    def __init__(self, specialist):
        self._specialist = specialist

    def detect(self, input_path, **options):
        return self._specialist.run("identity.face.detect", input_path, options)

    def embed(self, input_path, **options):
        return self._specialist.run("identity.face.embed", input_path, options)

    def verify(self, input_path, *, other_input, **options):
        return self._specialist.run("identity.face.verify", input_path, {**options, "other_input": str(other_input)})

    def compare(self, input_path, *, other_input, **options):
        return self._specialist.run("vision.face_compare", input_path, {**options, "other_input": str(other_input)})


class GeometryFacade:
    def __init__(self, specialist):
        self._specialist = specialist

    def _run(self, capability, input_path=None, **options):
        if input_path is not None:
            return self._specialist.run(capability, input_path, options)
        temporary = tempfile.NamedTemporaryFile(prefix="specialist-geometry-", suffix=".bin", delete=False)
        try:
            temporary.close()
            return self._specialist.run(capability, temporary.name, options)
        finally:
            Path(temporary.name).unlink(missing_ok=True)

    def distance(self, a, b, *, input_path=None):
        return self._run("vision.geometry.distance", input_path, a=a, b=b)

    def angle(self, a, vertex, c, *, unit="degrees", input_path=None):
        return self._run("vision.geometry.angle", input_path, a=a, vertex=vertex, c=c, unit=unit)

    def area(self, points, *, input_path=None):
        return self._run("vision.geometry.area", input_path, points=points)

    def contour(self, points, *, closed=True, input_path=None):
        return self._run("vision.geometry.contour", input_path, points=points, closed=closed)

    def homography(self, source, destination, *, input_path=None):
        return self._run("vision.geometry.homography", input_path, source=source, destination=destination)

    def perspective_transform(self, points, matrix, *, input_path=None):
        return self._run("vision.geometry.perspective_transform", input_path, points=points, matrix=matrix)

    def calibrate_camera(self, image_size, *, object_points=None, image_points=None, input_path=None):
        return self._run("vision.geometry.calibrate_camera", input_path, image_size=image_size, object_points=object_points, image_points=image_points)

    def solve_pnp(self, object_points, image_points, camera_matrix, *, distortion=None, input_path=None):
        return self._run("vision.geometry.solve_pnp", input_path, object_points=object_points, image_points=image_points, camera_matrix=camera_matrix, distortion=distortion)


class MediaFacade:
    def __init__(self, specialist):
        self._specialist = specialist

    def probe(self, input_path, **options):
        return self._specialist.run("media.probe", input_path, options)

    def extract_frames(self, input_path, **options):
        return self._specialist.run("media.video.extract_frames", input_path, options)

    def trim_video(self, input_path, *, start, end, **options):
        return self._specialist.run("media.video.trim", input_path, {**options, "start": start, "end": end})

    def transcode_video(self, input_path, **options):
        return self._specialist.run("media.video.transcode", input_path, options)

    def concat_video(self, inputs, *, input_path=None, **options):
        source = input_path or inputs[0]
        return self._specialist.run("media.video.concat", source, {**options, "inputs": list(inputs)})

    def extract_audio(self, input_path, **options):
        return self._specialist.run("media.audio.extract", input_path, options)

    def trim_audio(self, input_path, *, start, end, **options):
        return self._specialist.run("media.audio.trim", input_path, {**options, "start": start, "end": end})

    def resample_audio(self, input_path, *, sample_rate, **options):
        return self._specialist.run("media.audio.resample", input_path, {**options, "sample_rate": sample_rate})

    def convert_audio(self, input_path, *, format="wav", **options):
        return self._specialist.run("media.audio.convert", input_path, {**options, "format": format})

    def normalize_audio(self, input_path, **options):
        return self._specialist.run("media.audio.normalize", input_path, options)


class Specialist:
    """Small, synchronous SDK facade over the local runtime.

    The facade intentionally mirrors the capability names in the CLI while
    keeping the underlying provider implementation private and replaceable.
    """

    def __init__(self, home=None, provider_overrides=None, **runtime_options):
        self.runtime = SpecialistRuntime(home=home, provider_overrides=provider_overrides, **runtime_options)
        self.speech = SpeechFacade(self)
        self.human = HumanFacade(self)
        self.audio = AudioFacade(self)
        self.retrieval = RetrievalFacade(self)
        self.identity = IdentityFacade(self)
        self.geometry = GeometryFacade(self)
        self.media = MediaFacade(self)

    def run(self, capability, input_path, options=None):
        return self.runtime.run(capability, input_path, options or {})

    def detect(self, input_path, **options):
        return self.run("vision.detect", input_path, options)

    def segment(self, input_path, prompt=None, **options):
        if prompt is not None:
            options["prompt"] = prompt
        return self.run("vision.segment", input_path, options)

    def ocr(self, input_path, **options):
        return self.run("vision.ocr", input_path, options)

    def depth(self, input_path, **options):
        return self.run("vision.depth", input_path, options)

    def parse_screen(self, input_path, **options):
        return self.run("screen.parse", input_path, options)

    def parse_document(self, input_path, **options):
        return self.run("document.parse", input_path, options)

    def transcribe(self, input_path, **options):
        return self.run("audio.transcribe", input_path, options)

    def vad(self, input_path, **options):
        return self.run("audio.vad", input_path, options)

    def human_state(self, input_path, **options):
        return self.run("vision.human_state", input_path, options)

    def measure(self, input_path, **options):
        return self.run("vision.measure", input_path, options)

    def transcribe_video(self, input_path, **options):
        return self.run("media.transcribe_video", input_path, options)

    def speak(self, text, **options):
        return self.speech.synthesize(text, **options)

    def clone_voice(self, text, reference_audio, **options):
        return self.speech.clone_voice(text, reference_audio, **options)

    def graph(self, name="specialist-graph"):
        return SpecialistGraph(name)

    def cascade(self, name="specialist-cascade"):
        return SpecialistCascade(name=name)

    def open_session(self, capability, **options):
        return self.runtime.open_session(capability, options)


__all__ = ["Specialist", "SpeechFacade", "HumanFacade", "AudioFacade", "RetrievalFacade", "IdentityFacade", "GeometryFacade", "MediaFacade", "SpecialistRuntime", "SpecialistGraph", "SpecialistCascade", "ComputeNode", "NodeScheduler", "ProviderAdapter", "ProviderResult"]
__version__ = "1.1.0"

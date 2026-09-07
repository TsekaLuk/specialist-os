"""Isolated ROSVOT inference with a narrowly scoped, checked CPU portability patch."""
from __future__ import annotations

import ast
import io
import os
from pathlib import Path
import stat
import sys
import tempfile
import zipfile

from .ipc import WorkerError
from .optional import _run_external
from .optional_expansion import ExpansionOptionalProvider
from ..artifacts import ArtifactStore


def portable_source(source: str) -> str:
    """Patch only the two CUDA assumptions in the pinned upstream runner."""
    tree = ast.parse(source)
    changes = {"import": 0, "device": 0, "batch": 0}
    expected_device = ast.dump(ast.parse('torch.device(f"cuda:{int(rank)}")', mode="eval").body)
    expected_batch = ast.dump(ast.parse('move_to_cuda(batch, int(rank))', mode="eval").body)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "utils.commons.tensor_utils":
            node.names.append(ast.alias(name="move_to_cpu"))
            changes["import"] += 1
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name == "device" and ast.dump(node.value) == expected_device:
                node.value = ast.parse('torch.device(f"cuda:{int(rank)}" if torch.cuda.is_available() else "cpu")', mode="eval").body
                changes["device"] += 1
            elif name == "batch" and ast.dump(node.value) == expected_batch:
                node.value = ast.parse('move_to_cuda(batch, int(rank)) if device.type == "cuda" else move_to_cpu(batch)', mode="eval").body
                changes["batch"] += 1
    if changes != {"import": 1, "device": 1, "batch": 1}:
        raise ValueError("ROSVOT source does not match the reviewed portability contract")
    return ast.unparse(ast.fix_missing_locations(tree)) + "\n"


def extract_reviewed_zip(archive: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive) as source:
        entries = source.infolist()
        if sum(item.file_size for item in entries) > 2 * 1024**3:
            raise ValueError("ROSVOT archive exceeds its expanded size limit")
        for item in entries:
            relative = Path(item.filename)
            if relative.is_absolute() or ".." in relative.parts or stat.S_ISLNK(item.external_attr >> 16):
                raise ValueError("Unsafe ROSVOT archive entry")
        source.extractall(destination)


class RosvotProvider(ExpansionOptionalProvider):
    requires_verified_artifact = True
    supported_devices = ("cpu",)
    supported_platforms = ("macos-arm64", "linux-x64")
    license = "MIT code; M4Singer-trained checkpoint terms require separate review"
    REVISION = "3c8332bf43adae35f6e4d64971862f2f6139b310"

    def __init__(self):
        super().__init__("rosvot", "music.transcribe_vocal", "rosvot-m4singer-202406")

    def _check_dependency(self):
        for module in ("torch", "librosa", "pyworld", "pretty_midi", "yaml", "einops", "soundfile"):
            self._missing_dependency(module)

    def _load_model(self):
        self._check_dependency()

    def infer(self, input_path, options, cache):
        if options.get("device", "cpu") != "cpu":
            raise WorkerError("This portable ROSVOT route currently exposes CPU inference",
                              code="invalid_options", retryable=False)
        self.load()
        import pretty_midi
        import soundfile as sf

        info = sf.info(str(input_path))
        if not 0 < info.duration <= 180:
            raise WorkerError("Vocal transcription requires audio up to three minutes",
                              code="invalid_input", retryable=False)
        with tempfile.TemporaryDirectory(prefix="music-rosvot-") as temporary:
            directory = Path(temporary)
            extract_reviewed_zip(self.artifact_root() / "source.zip", directory)
            source = directory / f"ROSVOT-{self.REVISION}"
            extract_reviewed_zip(self.artifact_root() / "checkpoints.zip", source)
            runner = source / "inference/rosvot.py"
            runner.write_text(portable_source(runner.read_text()))
            output = directory / "result"
            environment = {**os.environ, "PYTHONPATH": str(source), "CUDA_VISIBLE_DEVICES": "", "MPLBACKEND": "Agg"}
            command = [sys.executable, str(runner), "-o", str(output), "-p", str(Path(input_path).absolute()),
                       "--sync_saving", "--no_save_every_npy", "--no_save_final_npy"]
            completed = _run_external(command, timeout=840, env=environment, cwd=source)
            path = output / "midi/output.mid"
            if completed.returncode or not path.is_file():
                raise WorkerError(f"ROSVOT transcription failed: {completed.stderr[-1500:]}",
                                  code="provider_error", retryable=False)
            data = path.read_bytes()
            midi = pretty_midi.PrettyMIDI(io.BytesIO(data))
            notes = [{"pitch": int(n.pitch), "start": float(n.start), "end": float(n.end),
                      "velocity": float(n.velocity) / 127} for i in midi.instruments for n in i.notes]
            notes.sort(key=lambda n: (n["start"], n["pitch"], n["end"]))
            ref = ArtifactStore(cache.artifacts).put_bytes(data, mime="audio/midi",
                metadata={"kind": "music/midi", "capability": self.capability})
        return {"notes": notes, "midi": ref.uri, "duration": info.duration,
                "artifacts": [ref.to_dict()], "warnings": [{"code": "EXPERIMENTAL_VOCAL_TRANSCRIPTION"}]}, []

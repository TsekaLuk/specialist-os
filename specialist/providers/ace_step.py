"""Local ACE-Step generation over a verified, immutable checkpoint bundle."""
from __future__ import annotations

import math
import os
import re
from pathlib import Path
import tempfile

from .ipc import WorkerError
from .optional_expansion import ExpansionOptionalProvider
from ..artifacts import ArtifactStore


class AceStepProvider(ExpansionOptionalProvider):
    requires_verified_artifact = True
    supported_devices = ("cpu", "mps", "cuda")
    supported_platforms = ("macos-arm64", "linux-x64")
    license = "MIT"
    memory_requirement_mb = 16000

    def __init__(self):
        super().__init__("ace_step", "music.generate", "ace-step-1.5-turbo-19671f40")

    def _check_dependency(self):
        for name in ("acestep", "torch", "soundfile"):
            self._missing_dependency(name)

    def _load_model(self):
        self._check_dependency()

    def infer(self, input_path, options, cache):
        duration = options.get("duration", 15)
        seed = options.get("seed", 42)
        instrumental = options.get("instrumental", True)
        lyrics = options.get("lyrics", "")
        device = options.get("device", "cpu")
        bpm = options.get("bpm")
        key = options.get("key", "")
        reference = options.get("reference_audio")
        provider_options = options.get("provider_options", {})
        if (bpm is not None and (isinstance(bpm, bool) or not isinstance(bpm, int) or not 30 <= bpm <= 300)
                or not isinstance(key, str) or key and not re.fullmatch(r"[A-G](?:#|b)? (?:major|minor)", key)
                or not isinstance(provider_options, dict) or provider_options):
            raise WorkerError("bpm must be 30..300, key must be e.g. C major; no provider-specific overrides are currently supported",
                              code="invalid_options", retryable=False)
        if (isinstance(duration, bool) or not isinstance(duration, (int, float))
                or not math.isfinite(duration) or not 10 <= duration <= 120
                or isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**32
                or not isinstance(instrumental, bool) or not isinstance(lyrics, str)
                or len(lyrics) > 4096 or device not in self.supported_devices):
            raise WorkerError("Expected duration 10..120 seconds, uint32 seed, boolean instrumental, lyrics up to 4096 characters and cpu/mps/cuda device",
                              code="invalid_options", retryable=False)
        path = Path(input_path)
        if path.stat().st_size > 8192:
            raise WorkerError("Music prompt file is too large", code="invalid_input", retryable=False)
        caption = path.read_text(encoding="utf-8").strip()
        if not caption or len(caption) > 512:
            raise WorkerError("Music prompt must contain 1..512 characters", code="invalid_input", retryable=False)
        if reference is not None:
            if not isinstance(reference, str) or not Path(reference).is_file():
                raise WorkerError("reference_audio must be a local audio file", code="invalid_options", retryable=False)
            import soundfile as sf
            try:
                reference_info = sf.info(reference)
            except (RuntimeError, OSError) as exc:
                raise WorkerError("Cannot decode reference_audio", code="invalid_input", retryable=False) from exc
            if not 0 < reference_info.duration <= 120 or reference_info.channels not in (1, 2):
                raise WorkerError("reference_audio must be mono or stereo and at most 120 seconds", code="invalid_input", retryable=False)
        self.load()
        from acestep.handler import AceStepHandler
        from acestep.inference import GenerationParams, GenerationConfig, generate_music
        import soundfile as sf

        # OptionalProvider.load verifies every bundle hash before this point.
        # Disable upstream download and source rewriting inside the bundle.
        class VerifiedHandler(AceStepHandler):
            def _ensure_models_present(self, *, checkpoint_path, config_path, **kwargs):
                required = ("Qwen3-Embedding-0.6B/model.safetensors",
                            "acestep-v15-turbo/model.safetensors", "vae/diffusion_pytorch_model.safetensors")
                if not all((checkpoint_path / name).is_file() for name in required):
                    return "Verified ACE-Step bundle is incomplete", False
                return None

            @staticmethod
            def _sync_model_code_if_needed(config_path, checkpoint_path):
                return None

        with tempfile.TemporaryDirectory(prefix="music-ace-") as temporary:
            previous = os.environ.get("ACESTEP_CHECKPOINTS_DIR")
            os.environ["ACESTEP_CHECKPOINTS_DIR"] = str(self.artifact_root())
            try:
                handler = VerifiedHandler()
                message, ready = handler.initialize_service(
                    project_root=temporary, config_path="acestep-v15-turbo", device=device,
                    use_flash_attention=False, compile_model=False, use_mlx_dit=device == "mps")
                if not ready:
                    raise WorkerError(f"ACE-Step initialization failed: {message}", code="provider_error", retryable=False)
                params = GenerationParams(caption=caption, lyrics=lyrics, instrumental=instrumental,
                    bpm=bpm, keyscale=key, reference_audio=reference,
                    duration=float(duration), seed=seed, inference_steps=8, thinking=False,
                    use_cot_metas=False, use_cot_caption=False, use_cot_language=False)
                generated = generate_music(handler, None, params,
                    GenerationConfig(batch_size=1, use_random_seed=False, seeds=[seed], audio_format="wav"),
                    save_dir=temporary)
                if not generated.success or len(generated.audios) != 1:
                    raise WorkerError(f"ACE-Step generation failed: {generated.error}", code="provider_error", retryable=False)
                audio = Path(generated.audios[0]["path"])
                info = sf.info(str(audio))
                if info.duration <= 0 or abs(info.duration - duration) > 2:
                    raise WorkerError("Generated audio duration does not match request", code="provider_error", retryable=False)
                ref = ArtifactStore(cache.artifacts).put_bytes(audio.read_bytes(), mime="audio/wav",
                    metadata={"kind": "music/generated", "capability": self.capability, "seed": seed})
            finally:
                if previous is None:
                    os.environ.pop("ACESTEP_CHECKPOINTS_DIR", None)
                else:
                    os.environ["ACESTEP_CHECKPOINTS_DIR"] = previous
        return {"audio": ref.uri, "duration": info.duration, "sample_rate": info.samplerate,
                "bpm_requested": bpm, "key_requested": key or None,
                "prompt": caption, "seed": seed, "instrumental": instrumental,
                "artifacts": [ref.to_dict()]}, []

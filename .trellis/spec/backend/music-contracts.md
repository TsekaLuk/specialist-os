# Music Pack Contracts

## 1. Scope

ADR-004 providers, shared result validation, install metadata and CLI rehearsal.
Music remains outside the frozen Core 15 / 56 API allowlist.

## 2. Signatures

`validate_music_result(capability: str, result: dict) -> None` is called by
`validate_envelope` for successful music.* envelopes. Providers return payloads
and warning arrays using the existing provider protocol.

## 3. Contracts

Notes use integer MIDI pitch 0..127, seconds with end > start, and optional
velocity/confidence 0..1. Stems are audio artifact references, never note arrays.
MIDI and descriptor references contain complete SHA256 artifact URIs. Music
artifact semantic kinds belong in artifact metadata, not invented MIME types.
Composite children preserve envelopes, including failure status and provenance.
Pack installation defers weights and reports `model_state=on_demand`, never a
ready installation marker. Explicit capability installation prepares weights.
Native capabilities remain weight-free in runtime, doctor and release checks.
Generation's `reference_audio` is an explicit local input, resolved and hashed
before cache lookup. The adapter checks mono/stereo and duration <= 120 seconds.
`bpm` and `key` are conditioning inputs, not output measurement claims.

Registry artifact kind `native` means no model weights exist. It cannot declare
download URLs, hashes or file bundles. Installed executable/package version is
the provider identity; native readiness must not demand nonexistent weights.
Basic Pitch uses Python 3.11, independently of the core interpreter.

## 4. Validation and Errors

- Negative/reversed/nonfinite note times or pitch outside MIDI range: reject.
- Waveform embedded under stems or a plain file path under midi: reject.
- Failed composite child with parent status ok: reject.
- Chromaprint missing or unsupported version: structured dependency/version error.
- Recording comparison: resolve and hash other_input before forming cache key.
- Invalid requested model must fail even when a ready marker already exists.
- Download auth: only exact HTTPS huggingface.co requests may receive local HF
  credentials, using unredirected headers so CDN redirects do not inherit them.
- Rehearsal merge: different input hashes or artifact homes must not be combined.

## 5. Cases

Good: reuse cached comparison only when both recording contents match.
Base: report missing optional dependency while other capabilities remain usable.
Bad: mark model ready because a package imports, or use another run's MIDI.

## 6. Required Tests

Run tests/test_music_contracts.py, tests/test_core_scope.py and real native CLI
tests with SPECIALIST_RUN_MUSIC_E2E=1. Assert artifact resolution, uncached
repeatability and cache invalidation after replacing the secondary file.
Use scripts/rehearse_music.py for licensed source recordings; this is not an
accuracy benchmark without reference labels.
Run `scripts/benchmark_music.py` against the twelve category manifest. Preserve
source attribution and transformations, including controlled degradation. Keep
accuracy null without reference labels. Repeat runs retain unselected records.
`tests/test_music_installation.py` checks origin-bound credentials, deferred
weights, release metadata and requested-model validation. Native E2E must verify
stable execution after an experimental provider fails.

## 7. Wrong vs Correct

Wrong: resolve a virtualenv interpreter symlink with Path(python).resolve(),
then claim its packages are unavailable when the base interpreter runs.
Correct: use Path(python).absolute() for the command, preserving the venv path.

Wrong: call any artifact-free provider server-managed to bypass weight checks.
Correct: distinguish native algorithms from remote/server-owned weights.

Wrong: identify audio by a guessed filename or image alt text during publishing.
Correct: `publish_workspace.py` matches top-level envelope artifact hashes;
the slide exporter matches waveform bytes because image alt text is not retained
by the current presentation exporter. `check_slide_media.py` verifies embedded
bytes, local relationships, click timing and full decoding after finalization.

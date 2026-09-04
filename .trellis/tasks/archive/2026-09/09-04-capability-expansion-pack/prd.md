# Specialist Capability Expansion Pack

## Goal

Expand Specialist OS from its current perception runtime into a local-first
machine perception, measurement, retrieval, and deterministic media layer.
Keep the existing result envelope and provider isolation contract stable while
adding the capability families defined by ADR-PRD-002.

## Background

The repository currently exposes ten registered capabilities through one
registry, one runtime router, Python SDK facades, CLI aliases, optional
provider environments, content-addressed artifacts, and isolated JSONL
workers. New capabilities must use those same boundaries rather than creating
parallel execution paths.

## Requirements

### Capability surface

- Add human perception capabilities: `human.pose`,
  `human.hand_landmarks`, `human.face_landmarks`, and `human.gesture`.
- Add speech/audio capabilities: `speech.diarize`, `speech.align_transcript`,
  `speech.meeting`, and `audio.denoise` with `light`, `balanced`, and `strong`
  profiles. Preserve original audio artifacts and return processed audio as an
  artifact reference.
- Add visual semantics: `vision.embed`, `vision.embed_text`,
  `vision.similarity`, `vision.search`, and `vision.find_similar`.
- Add sensitive face identity capabilities: `identity.face.detect`,
  `identity.face.embed`, `identity.face.verify`, and `vision.face_compare`.
  Face verification must return a provider-calibrated threshold and must never
  turn an unavailable provider into a positive match.
- Add deterministic vision operators under `vision.geometry.*` and
  `vision.transform.*`, including distance, angle, area, contour,
  homography, feature matching, perspective transform, camera calibration,
  PnP, crop, resize, rotate, warp, colorspace, blur, and threshold.
- Add deterministic media capabilities: `media.probe`, video frame
  extraction/trim/transcode/concat, audio extraction/trim/resample/convert/
  normalize, and `media.transcribe_video`.
- Upgrade `vision.depth`/`spatial.depth` semantics with `mode=relative` and
  `mode=metric`; relative results must have no distance unit and metric results
  must explicitly report `unit="meter"` and estimated status.
- Add `vision.human_state` and `vision.measure` composites that combine the
  existing perception outputs with new human/depth/geometry capabilities.

### Provider and runtime behavior

- Register default providers: MediaPipe Tasks, pyannote.audio, DeepFilterNet,
  OpenCLIP/SigLIP2, InsightFace, OpenCV, and FFmpeg.
- Keep heavyweight model packages and weights lazy. `install core` registers
  all capability metadata but does not download every model; first use may
  create the isolated provider environment and fetch only a verified registry
  artifact.
- Keep provider names out of normal user-facing capability names. Provider
  overrides remain available only through explicit developer options.
- Mark capability metadata with `streaming`, `stateful`, `deterministic`,
  `sensitive`, input/output schemas, privacy level, model profiles, and
  quality metrics.
- Reject raw shell commands and arbitrary OpenCV code from all public APIs.
  FFmpeg and image transforms must build validated argument vectors internally.
- Preserve provider failure isolation: a missing dependency, crash, OOM, or
  malformed result produces a structured error for that capability and cannot
  corrupt existing capability execution.

### Artifacts, cache, and observability

- Support artifact metadata for `image/*`, `video/*`, `audio/*`,
  `embedding/*`, `landmarks/*`, and `timeline/*`.
- Collect generated files and frame/audio lists into the content-addressed
  artifact store without embedding binary data in JSON.
- Cache embeddings by input hash, model hash, and preprocessing version;
  disable face-embedding cache unless `allow_sensitive_cache=true` is
  explicitly supplied. Cache deterministic media transforms by input and
  normalized options.
- Include provider/model provenance, deterministic flag, privacy level,
  confidence, metrics, and composite trace entries in every result.

### Interfaces and operations

- Expose stable Python SDK facades for all new families and typed convenience
  methods for the common composites.
- Expose CLI commands/aliases for each callable capability, JSON output, and
  safe typed options. `capabilities`, `doctor`, `models`, `pack`, HTTP, MCP,
  and Compute Node surfaces must discover the expanded registry.
- Add packs named `human`, `identity`, `audio-plus`, `retrieval`, `media`, and
  `core`; retain existing pack names and aliases.
- Extend doctor with dependency readiness, selected model profile, hardware
  suitability, FFmpeg/OpenCV checks, sensitive capability status, and
  actionable installation guidance.

## Acceptance Criteria

- [x] Registry validates and exposes every capability and pack above with one
      recommended model per capability and complete capability metadata.
- [x] Existing ten capability tests and aliases remain compatible.
- [x] `human.pose`, `human.hand_landmarks`, `human.face_landmarks`, and
      `human.gesture` support one-shot and stateful session calls; missing
      MediaPipe returns a clear dependency error or explicit fallback warning.
- [x] `speech.diarize` emits normalized speaker timelines; alignment joins
      timestamped transcript segments without LLM speaker guessing.
- [x] `audio.denoise` preserves the source, returns an audio artifact, reports
      duration/sample rate/channels, and supports all three strength profiles.
- [x] Image-to-image, text-to-image, and corpus search return ranked results;
      embeddings are stored as artifacts and never placed inline in the normal
      LLM result.
- [x] Face verification returns `match`, `similarity`, `threshold`, and
      profile/status fields, with sensitive defaults (`local_only`, no
      persistence, no telemetry, no cache).
- [x] Geometry operations pass distance, angle, area, perspective transform,
      homography, and feature-matching correctness tests; deterministic
      metadata is true for deterministic operators.
- [x] Media operations pass probe, frame extraction, audio extraction, trim,
      transcode, resample, convert, and normalize tests using safe typed options.
- [x] Depth results distinguish relative and metric modes, units, and
      estimated status in both runtime and JSON schema validation.
- [x] Composite capabilities execute through the runtime, preserve child
      provenance/artifacts, and expose an ordered trace.
- [x] `specialist capabilities`, `specialist doctor --json`, `specialist install
      core`, SDK, HTTP, MCP, and node capability lists include the expanded
      surface without eagerly importing heavyweight dependencies.
- [x] Provider crash/OOM/missing-dependency tests demonstrate isolation from
      the original capability set.
- [x] Full unit, E2E, schema, release, and package checks pass on the supported
      Apple Silicon environment; documentation describes install profiles,
      privacy, licensing, and production rollout.

## Out of Scope

RTMPose, CoTracker, LightGlue, COLMAP, SLAM, super-resolution, barcode/EXIF
specialists, source separation, music/video generation, vector database
implementation, and the future Spatial/3D Pack remain expansion work.

# Technical Design

## Architecture

The registry remains the single source of capability truth. Each registry
entry describes one callable capability, its provider candidates, model
profiles, resource/privacy/determinism metadata, and wire schemas. Runtime
routing, policy evaluation, cache keys, artifact collection, observation
construction, HTTP/MCP dispatch, and node advertisement consume that registry
without capability-specific registries.

New code is grouped by responsibility:

- `specialist/providers/expansion.py`: dependency-free providers for typed
  geometry, media, artifact preparation, and explicit fallback responses.
- `specialist/providers/optional_expansion.py`: lazy adapters for MediaPipe,
  pyannote, DeepFilterNet, OpenCLIP/SigLIP2, and InsightFace. Imports happen
  only after provider selection and installation.
- `specialist/composites.py`: runtime-owned composition helpers. They call
  child capabilities through `SpecialistRuntime.run`, preserve child result
  metadata, and return an ordered trace.
- `specialist/media.py` and `specialist/geometry.py`: validated typed argument
  builders shared by fallback and optional providers; no raw command strings
  cross the public API.

Existing `BuiltinProvider`, `OptionalProvider`, `JsonlProcessProvider`, and
`SpecialistRuntime` lifecycle paths remain the only provider execution paths.
Composite providers are marked stateful at the runtime boundary and are not
wrapped in a second worker; their child providers retain normal isolation.

## Data Flow

### One-shot capability

```text
CLI/SDK/HTTP/MCP
  -> resolve_capability + validate options
  -> policy + deterministic router
  -> lazy install / provider environment
  -> provider.infer(path, typed options)
  -> normalize result payload
  -> collect files into ArtifactStore
  -> observations/evidence/provenance/metrics
  -> schema validation + cache
```

### Composite capability

```text
composite input
  -> child runtime.run calls
  -> typed child envelopes
  -> merge result/artifacts/provenance
  -> trace[{capability, provider, status}]
  -> one parent envelope
```

### Artifact boundary

Providers return small JSON objects containing output paths or structured
metadata. Runtime promotes files to content-addressed artifacts and rewrites
known output fields (`audio`, `frames`, `files`, `embedding_path`, etc.) to
`artifact://` references. Binary payloads never cross the JSONL, HTTP, MCP, or
LLM boundary.

## Capability Contracts

### Human

Normalized landmark items use `{name, x, y, z, visibility, confidence}` in
normalized image coordinates. Streaming sessions reuse the loaded provider;
fallback sessions return an explicit unavailable warning and no fabricated
landmarks.

### Speech/audio

Timelines use `{speaker|label, start, end, confidence}` with seconds from zero.
`speech.align_transcript` joins overlapping timestamp intervals and never calls
an LLM. Denoise returns an audio artifact plus duration, sample rate, channels,
and profile; source and processed artifacts remain separate.

### Embeddings and identity

Embedding payloads contain only an artifact URI, dimension, normalization,
model, and status. Search returns ranked references with scores. Face identity
is local-only by default, non-persistent, non-telemetry, and uncached unless
`allow_sensitive_cache=true`. Verify returns nullable match when unavailable,
the calibrated threshold, profile, and provider status.

### Deterministic geometry/media

Geometry input points, matrices, and options are validated before calculation.
The math implementation is pure Python where possible and OpenCV is used when
available for image algorithms. Media uses `ffprobe`/`ffmpeg` with an internal
argument allow-list and process-group timeout. All deterministic results set
`deterministic=true` in result metadata and provenance.

### Depth

`mode` defaults to `relative` for backward compatibility. Relative responses
include `unit: null`; metric responses include `unit: "meter"` and
`estimated: true`. A metric request is rejected when the selected provider does
not advertise metric support rather than silently relabeling relative depth.

## Registry and Installation

Model entries use server-managed artifacts for providers that download their
own upstream assets and pinned file/bundle artifacts where the project can
verify them. Capability packs are derived from registry bundle names. `core`
contains the original capabilities plus all new base capabilities; composite
entries are installed lazily with their dependencies.

Provider environments are extended with pinned package requirements, but the
core interpreter never imports heavy packages at module import time. Doctor
reports dependency, executable, model profile, platform, memory, and privacy
state without loading models.

## Compatibility and Rollback

- Existing capability names, command aliases, result envelope keys, and cache
  identities remain valid.
- Existing depth calls keep relative semantics unless `mode="metric"` is
  explicit.
- Existing packs (`vision`, `audio`, `document`, `all`) remain available.
- New registry entries can be rolled back independently by removing their
  providers/pack entries; the original provider map remains usable.
- Every new provider is optional or deterministic and has an isolated failure
  boundary, so a failed expansion cannot prevent existing capabilities from
  routing or starting.

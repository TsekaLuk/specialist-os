# Changelog

## Unreleased

## 1.1.1

- Declared provider prerequisites as data that can be read without importing
  provider code. Interchangeable sources share a group and the group is satisfied
  when any member is, so a credential readable from either an environment
  variable or a file no longer reports the unused source as missing.
- Added the `degraded` capability status: installed and routable, but a
  non-optional prerequisite is unmet, so the call is accepted and fails at
  execution. `doctor` now names the unmet requirement instead of printing a bare
  status word. Existing status values are unchanged.
- Self-check no longer contacts declared endpoints. A registered but offline
  remote node or speech server previously stalled `specialist doctor` for seconds
  per capability; it is now reported as declared-but-unprobed. Pass
  `specialist doctor --probe-endpoints` to contact them explicitly.
- BEHAVIOR CHANGE: `/ready` and `/v1/ready` probe declared endpoints and return
  503 when one is unreachable or reports itself unhealthy. Deployments whose
  orchestrator reads `/ready` will start draining a node whose remote capability
  backend or Fish Audio server is down. Probes are deduplicated per distinct
  endpoint with a 1s budget each. `/studio` stays unprobed and says so.
- Endpoint health predicates travel with the URL, so a node answering 200 with an
  unhealthy body is reported unhealthy rather than ready.
- Requirements are probed in the provider's own environment, fixing a false
  missing-prerequisite report for console scripts installed in isolated provider
  environments.
- A malformed third-party provider manifest now drops only its own requirements
  and is named in the report warnings, instead of silently clearing every
  provider's requirements.
- Fixed the package E2E capability assertion, which compared the combined Core
  plus Music list against the Core-only baseline. Core and the Music pack are now
  asserted as separate counts that partition the list, keeping the ADR-003 scope
  freeze enforced by CI.

## 1.1.0

- Expanded Specialist OS to 56 local-first capabilities spanning human pose,
  landmarks, gestures, diarization, denoising, embeddings, face verification,
  deterministic geometry, media transforms, depth, and composed workflows.
- Added MediaPipe, pyannote.audio, DeepFilterNet, OpenCLIP, InsightFace,
  OpenCV, FFmpeg, and Fish Audio integrations behind isolated provider
  environments and the shared result envelope.
- Added content-addressed outputs for audio, video, images, embeddings,
  landmarks, and timelines, with sensitive face-identity caching disabled by
  default.
- Added a bilingual product guide and a real CLI-generated capability gallery
  with playable audio results and provider/model provenance.
- Added typed Python, CLI, HTTP, MCP, and Compute Node discovery surfaces for
  the expanded registry while preserving the existing SDK and protocol names.
- Hardened verified model downloads with bounded retries, resumable transfers,
  content-length checks, and mandatory SHA256 verification.
- Completed the Fish Audio S2 provider contract: official Server request fields,
  style controls, reference artifacts, remote-node resource routing, audio
  validation, speech performance metrics and live-server E2E coverage.
- Hardened real-provider installation and acceptance: pinned provider
  environments, offline command-provider boundaries, venv console-script PATH
  handling, PaddleOCR PP-OCRv5 compatibility, and process-group cleanup on
  timeout.

## 1.0.4

- Fixed the heavy-provider acceptance workflow so `run_heavy=true` executes
  the Depth Anything inference test instead of silently skipping it.

## 1.0.3

- Disable the PaddleOCR oneDNN executor for the pinned PP-OCRv5 CPU bundle.

## 1.0.2

- Disable the unsupported PaddlePaddle oneDNN path for PP-OCRv5 CPU bundles.
- Raise the isolated SAM2 virtual-memory budget and propagate operator provider
  configuration through worker process boundaries.

## 1.0.1

- Production hardening release for real-provider environments and acceptance
  workflows.

- Added process-boundary E2E coverage for the CLI, HTTP API, MCP stdio server,
  isolated workers and optional wheel installation.
- Added provider-aware readiness and a `doctor --strict` deployment gate.
- Added release metadata validation and systemd/launchd service templates.
- MCP SIGTERM now exits cleanly without emitting a traceback or non-JSON
  stdout.
- Added pinned upstream model artifacts, atomic multi-file bundle manifests,
  integrity re-checks before provider load, uv dependency locking, SBOM
  generation and build provenance attestations.

## 1.0.0

- Production release with audited registry artifacts for all eight capability
  providers and opt-in real-provider integration coverage.

## 0.2.0

- Added a validated capability/model registry with provenance and license metadata.
- Added atomic, checksum-verified model artifacts and lifecycle/error state reporting.
- Added isolated provider environments with import verification.
- Hardened JSONL workers, HTTP request handling, concurrency limits and shutdown cleanup.
- Added typed result validation and published capability result schemas.
- Added Rust cache-key/input-safety primitives and wheel/SDist build verification.

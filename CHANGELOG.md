# Changelog

## Unreleased

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

# Changelog

## Unreleased

- Added process-boundary E2E coverage for the CLI, HTTP API, MCP stdio server,
  isolated workers and optional wheel installation.
- MCP SIGTERM now exits cleanly without emitting a traceback or non-JSON
  stdout.

## 0.2.0

- Added a validated capability/model registry with provenance and license metadata.
- Added atomic, checksum-verified model artifacts and lifecycle/error state reporting.
- Added isolated provider environments with import verification.
- Hardened JSONL workers, HTTP request handling, concurrency limits and shutdown cleanup.
- Added typed result validation and published capability result schemas.
- Added Rust cache-key/input-safety primitives and wheel/SDist build verification.

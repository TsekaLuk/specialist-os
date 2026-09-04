# Implementation Plan

## Ordered Work

1. Extend registry dataclasses, aliases, bundle derivation, and
   `registry/models.yaml` with all base, operator, media, and composite
   capabilities plus metadata and model profiles.
2. Add the shared typed geometry and media helpers. Implement safe validation,
   pure math operations, ffprobe parsing, process timeouts, and artifact path
   handling.
3. Add dependency-free expansion providers and optional provider adapters;
   update provider selection and isolated-worker environment requirements.
4. Add depth mode handling, expanded artifact collection, sensitive cache
   policy, deterministic/provenance metadata, and composite orchestration.
5. Extend result validation and JSON schemas for landmarks, timelines,
   embeddings, face verification, geometry, media, and composites.
6. Extend Python SDK facades and CLI commands/aliases. Verify HTTP, MCP, node,
   doctor, models, and pack discovery use the same registry.
7. Add focused unit tests for contracts, pure math, media fixtures, artifact
   conversion, cache/privacy behavior, provider isolation, and composite
   traces; add real-provider tests guarded by dependency availability.
8. Update README and deployment docs with capability map, install packs,
   privacy/licensing boundaries, and production provider setup.

## Validation Commands

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 -m unittest discover -s tests/e2e -p 'test_*.py' -v
python3 -m compileall specialist
python3 scripts/release_check.py --require-artifacts
specialist capabilities --json
specialist doctor --json
specialist pack list
```

Additional checks:

```bash
python3 -m specialist --backend fallback geometry-distance fixture.json --json
python3 -m specialist --backend fallback media-probe fixture.mp4 --json
```

The media commands are skipped when `ffprobe` is unavailable; the test must
assert a structured `dependency_missing` result rather than silently passing.

## Review Gates

- Registry loads without importing heavy providers.
- Every capability has exactly one recommended model and valid artifact
  metadata.
- Every public media/image operation has a typed options validator and no
  shell escape path.
- Result payloads validate before caching and after cache replay.
- Sensitive face data never enters logs or default cache.
- Existing ten-capability regression suite remains green.
- Provider failure tests demonstrate isolation and actionable error codes.
- Documentation and release checks reflect the expanded registry.

## Rollback Points

- Revert registry/provider map changes to restore the original ten-capability
  runtime.
- Keep new schema definitions additive so old cached envelopes remain readable.
- Remove only expansion pack markers to disable eager discovery while retaining
  deterministic helpers for a staged rollout.

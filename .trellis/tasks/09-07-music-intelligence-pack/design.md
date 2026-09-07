# Music Pack Design

## Boundaries

Reuse specialist/packs.py, registry, ProviderEnvironmentManager, provider IPC,
result envelopes and artifact storage. Do not extend Core allowlists. Heavy
imports remain inside isolated provider execution, never discovery or startup.
Inspect each upstream API, license and pinned artifact before implementing its
adapter; upstream examples are API evidence, not demonstration outputs.

## Data Flow

CLI/MCP capability request -> validated options and explicit input -> isolated
provider -> normalized schema -> content-addressed artifacts -> result envelope
-> benchmark evidence and product workspace. No arbitrary shell argument surface.

## Contracts

Keep stems, notes, instrument tracks, scores and fingerprints distinct. Local
recording comparison is fingerprint-based, not semantic similarity. Store large
arrays as artifacts; preserve confidence/warnings for uncertain transcription.
Maturity and heavy-generation classification are independent metadata fields.
An installed environment is not proof of ready weights or successful inference.

## Compatibility

Existing frontend changes are unrelated unfinished work and must be preserved.
New demo generation must publish built frontend assets without deleting evidence.
Do not replace missing output with an input image or another run's artifact.

## Rollout

Gate public showcase additions on actual CLI E2E. Keep stable providers useful
when optional providers are absent. Record platform/install failures explicitly.
Rollback removes Music registration without touching Core or existing artifacts.

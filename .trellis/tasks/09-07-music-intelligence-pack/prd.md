# ADR-004 Music Intelligence Pack

## Goal

Implement the accepted ADR-004 Music Intelligence Pack and synchronize all
product-facing surfaces. Source: /Users/tseka_luk/Downloads/ADR-004-music-intelligence-pack.md.

## Requirements

- Keep the frozen Core 15 / 56 API baseline unchanged.
- Add music.analyze (Essentia), music.separate (audio-separator),
  music.fingerprint (Chromaprint), music.transcribe_notes (Basic Pitch),
  music.transcribe_multitrack (MuScriptor), music.transcribe_vocal (ROSVOT),
  and music.generate (ACE-Step 1.5), plus local recording comparison.
- Isolate stable, experimental, and generation installs; download verified
  model assets on demand. Preserve model license restrictions and maturity.
- Normalize music outputs using shared schemas and artifact-backed media,
  MIDI, MusicXML, analysis, and fingerprints. Never fabricate inference results.
- Update CLI, discovery/MCP, doctor, installation, registry, Agent Skill,
  bilingual README, capability workspace, live demo runbook and slides.
- Benchmark real recordings across the 12 ADR fixture categories; report
  accuracy only when reference annotations support the metric.
- Leave VocalParse and YourMT3+ on the watchlist. No DAW or score editor.

## Acceptance Criteria

- [x] All 12 acceptance criteria in ADR-004 section 24 pass with traceable evidence.
- [x] Core install and discovery regression tests retain their frozen scope.
- [x] Experimental provider failures do not affect stable capability execution.
- [x] Real CLI E2E runs preserve commands, input hashes, models and artifacts.
- [x] Demo audio is playable; MIDI/analysis views represent the same run.
- [x] Workspace screenshots and built entrypoints are verified in the browser.
- [x] README, Skill, slides and runbook describe only verified capabilities.

## Confirmed Composite Scope

The user approved both music.parse_singing and music.transcribe_full on
2026-09-07. Include both after their constituent providers pass real E2E;
preserve child envelopes and do not automatically reconcile competing scores.

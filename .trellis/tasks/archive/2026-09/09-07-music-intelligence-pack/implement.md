# Implementation Plan

- [x] Read ADR and inspect existing pack, provider and environment mechanisms.
- [x] Resolve optional composite scope and converge planning artifacts.
- [x] Archive the accepted ADR in docs/adr and activate this task.
- [x] Verify upstream APIs, versions, hashes, licenses and platform prerequisites.
- [x] Add shared Music schemas, provider metadata and independent install packs.
- [x] Implement stable provider adapters and local fingerprint comparison.
- [x] Implement isolated MuScriptor, ROSVOT and ACE-Step adapters.
- [x] Connect CLI/MCP discovery, doctor and capability-first options.
- [x] Add approved composites with retained child evidence.
- [x] Build licensed real fixture manifest and benchmark metric evaluation.
- [x] Run real CLI E2E; preserve errors and exclude failed showcases.
- [x] Update Skill, English/Chinese README, workspace, slides and runbook.
- [x] Verify build, browser media and focus states, unit/E2E and Core regression.
- [x] Review diff, update executable specs and report exact remaining blockers.

## Current Progress

All seven providers and both composites are implemented, covering ten Music
capabilities including recording comparison. Every capability has successful
real isolated CLI evidence. MuScriptor access was granted. Managed environment
installation for MuScriptor and ROSVOT was repaired and exercised locally.
Independent install packs, lazy weight preparation, shared discovery schemas,
and grouped doctor output are implemented. Core remains 15 families / 56 APIs.

Evidence: output/music-singing-rehearsal, output/music-generation-rehearsal,
output/music-workflow-rehearsal. Complete listening page:
output/demo/music-singing/index.html. Desktop and mobile playback checks pass.
Final full suite: 186 passed, 11 skipped, 7 subtests passed, with one existing
pytest return-value warning. Isolation/publication/install tests also passed
independently (17 tests).

Completed: 12-category benchmark (72 successful real runs), ACE-Step
BPM/key/reference-audio controls (36.935 seconds for the recorded run), gated
Hugging Face credential handling, release/install checks, responsive workspace
and playable audio, and Skill synchronization. Core remains unchanged.
README, Music documentation and runbook describe all ten verified paths.
Slides v5 includes six embedded audio results on slides 9 and 12; package
relationships, hashes and full audio decoding pass. Native presentation-app
playback has not been verified. Benchmark accuracy is not asserted without
reference annotations. Evidence snapshot: docs/music-regression.json.

Silent Codex recording has not started: Computer Use explicitly denied access
to the Codex native app. This is a separate blocked delivery, not a completed
recording. No alternative capture route is used to bypass the denial.

## Verification

Run targeted Music contract tests, tests/test_core_scope.py, CLI/MCP integration
tests, the full existing suite, compileall and release checks. Music benchmark
commands must use backend=real and isolated execution. No dependency-presence
probe substitutes for a successful inference. Slides require rendered review;
workspace requires desktop/mobile checks against the actually served build.

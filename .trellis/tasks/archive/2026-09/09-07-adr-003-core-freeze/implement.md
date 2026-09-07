# Implementation

- [x] Freeze Core membership and expose family metadata in discovery.
- [x] Clarify pack names while retaining legacy resolution.
- [x] Add ADR, watchlist and scope/roadmap documentation.
- [x] Add and run targeted regressions, full unit/E2E suites and compile checks.
- [x] Review diff, record verified results and outstanding limitations.

Rollback: revert only these task changes; no model installs or migrations occur.

## Verification

- Core scope regressions: 7 passed.
- Full unittest discovery: 126 total, 116 passed, 10 opt-in skips.
- Separate E2E discovery: 24 total, 14 passed, 10 opt-in skips (overlaps full suite).
- Real OpenCV E2E: ORB matching, PnP and warp passed with the existing YOLO
  environment and SPECIALIST_RUN_REAL_PROVIDER_E2E=1, selected provider opencv.
- compileall, release_check.py --require-artifacts, and git diff --check passed.
- Accepted ADR source compared verbatim (apart from trailing whitespace).
- New work does not install spatial/generative providers or claim their readiness.

Implementation complete. Phase 3.4 commit approved by the user. Existing demo,
Skill, provider fixes and transparent-logo work remain outside this task.

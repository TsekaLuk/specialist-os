# Implementation

- [x] CI/release pytest and frontend unit/typecheck/build gates.
- [x] Command quoting, copy failure state, read-only inspector.
- [x] Channel conversion and real media regression.
- [x] Full tests, build, published browser checks for the first repair batch.
- [ ] Clean-environment demo/slides reconstruction.
- [ ] Unified capability workspaces.
- [ ] Native presentation playback and permitted recording.

No push. Existing .cache and unused field.tsx are outside this task.

## First Batch Verification

- Full suite with native Music enabled: 187 passed, 11 skipped.
- Isolated Python environment with pytest only: 184 passed, 14 skipped.
- Both retain the existing test_environment return-value warning.
- Frontend shell argument round-trip: 2 passed; typecheck and Vite build pass.
- Published 8742 workspace: playback, copy, visible focus and no overflow pass
  at 1440/768/390; mobile screenshot reviewed.
- release_check.py --require-artifacts and git diff --check pass.
- GitHub workflows were edited but have not run remotely (no push).

Browser checks are still local, not a CI job. Broader reconstruction, unified
execution workspace, native playback and permitted recording remain open.

## Component Normalization

Badge, Button and Input now follow reviewed shadcn open-code contracts inside
the project infrastructure layer. Feature code consumes the canonical design
system API; styles and state geometry belong to components.css, not main.tsx.
AST tests guard native-control and direct-infrastructure leakage. Both published
HTML entrypoints use the same bundle. Browser checks include Badge alignment
and decoded YOLO previews at desktop/tablet/mobile sizes.

Rebuilt previews from existing CLI envelopes. The underlying gallery contains
33 cached results; cached replay is explicitly labeled and does not count as a
fresh rehearsal. Six transform previews have no recoverable local artifact and
remain marked unavailable, not replaced. Old records without original argv may
offer a replay command reconstructed from retained routing options and a
SHA-verified input, explicitly distinguished from a recorded command.

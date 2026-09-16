# Implementation

- [x] CI/release pytest and frontend unit/typecheck/build gates.
- [x] Command quoting, copy failure state, read-only inspector.
- [x] Channel conversion and real media regression.
- [x] Full tests, build, published browser checks for the first repair batch.
- [ ] Clean-environment demo/slides reconstruction.
- [ ] Unified capability workspaces.
- [ ] Native presentation playback and permitted recording.
- [x] Doctor requirement model: interchangeable sources and a probe policy.
- [x] Doctor status: separate degraded capabilities from unavailable ones.

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

## Input and Result Presentation

Input publication matches local asset bytes to envelope.input.sha256. Retained
input text may be displayed only when its UTF-8 SHA matches the same digest.
All 56 current Core pages have a verified input (55 files and one text input).
Audio transcription now displays the source player, full transcript and segment
table before the JSON disclosure. Input media and transcript are canonical
design-system patterns. Browser tests cover muted source playback and visible
segments at 1440/768/390. No inference was rerun for this presentation change.

## Doctor Requirement Model

Adapted from the `@crosery/dsh-ct` self-check contract (`oh-my-dsh`,
`plugins/crosery-tools/src/contract.ts`). Two properties transfer; its hot-swap
and unsandboxed execution model do not.

Declare prerequisites as data next to the provider, with `kind` in
`binary` / `env` / `file` / `endpoint`, a `purpose` string, `optional`, and a
`group` label. Requirements sharing a group are interchangeable and the group is
satisfied when any member is. A ModelScope-style credential readable from either
an environment variable or a credential file is one requirement with two
sources; reporting the unused source as missing raises a false alarm on a
capability that works.

Probe by kind: `binary` against PATH, `env` against the environment, `file`
against existence. Never contact an `endpoint` during a self-check. Report it as
declared-but-unprobed, and let the first real call surface reachability.

`RemoteNodeProvider.doctor` currently issues `GET {endpoint}/health` with a 3s
timeout, and the Fish Audio lifecycle health check adds its own. Both
`SpecialistRuntime.doctor` and `SpecialistRuntime.readiness` call
`provider.doctor` once per capability in a loop, so a configured but offline
remote node stalls the whole report for seconds per capability. Blocking on an
unreachable host is worse than admitting the endpoint was not checked.

Keep probes off the default path; an explicit opt-in flag may contact endpoints
when the operator asks for it.

## Doctor Status Levels

`doctor` currently collapses every non-ready outcome into `unavailable`, and
`_human_doctor` prints the status word without the reason. Distinguish the state
where a capability is installed and routable but a declared non-optional
requirement is missing: the capability is still exposed through the CLI, HTTP and
the DeepSeek Harness tool table, the call is accepted, and it fails at execution.
That is a different operator action from "not installed" and from "load failed".

Report which requirement or group is unmet, and where a previous working
installation remains in service. Preserve the existing states; add the degraded
level and carry the reason into human output.

### Validation

- `specialist doctor --json` on a host with a registered, offline remote node
  completes without per-capability endpoint timeouts.
- `specialist doctor` prints the unmet requirement or group for every capability
  that is not ready.
- A capability whose only missing prerequisite is optional stays ready.
- A grouped requirement satisfied by one member alone reports no gap.
- Full pytest suite and `release_check.py --require-artifacts`.

## Doctor Verification

Measured on this host with pytest 8.4.2 in the repository virtualenv.

- Full suite 207 passed, 14 skipped (192 passed, 14 skipped without the new
  file); the pre-existing test_environment return-value warning remains.
- `release_check.py --require-artifacts` and `git diff --check` pass.
- A registered, offline remote node serving eight capabilities: default
  `doctor --json` completes in 0.14s; `doctor --probe-endpoints` takes 24.6s and
  reports the same capabilities as unavailable with reason "timed out". The
  default report marks the node declared-but-unprobed.
- On this host the whisper group is satisfied by the binary alone
  (`/opt/homebrew/bin/whisper-cli`, `SPECIALIST_WHISPER_BINARY` unset) and the
  MinerU model group by `~/mineru.json` alone; neither reports a gap.
- An installed pyannote capability without a Hugging Face token reports
  `degraded` and names `huggingface-token (env HF_TOKEN or env
  HUGGINGFACE_HUB_TOKEN or env HUGGING_FACE_HUB_TOKEN or file
  ~/.cache/huggingface/token)` in `--json` and in human output. pyannote
  declares no optional requirement; the optional-source case is covered by the
  Fish Audio token and by unit tests.
- Endpoint contact is off the default path in `doctor` and `readiness`, so the
  HTTP `/ready` route no longer depends on remote reachability.

### Check Pass

Re-verified independently; three defects were found and fixed in place.

- Requirements were probed in the parent process environment, so a console
  script installed inside an isolated provider environment looked missing. On
  this host `document.parse` reported a bogus `mineru-command` gap while the
  worker resolves `mineru` from its own PATH; a capability one state away from
  being wrongly marked `degraded`. Probing now uses the provider's environment.
- Human output hid an unmet requirement behind the provider message and never
  showed a declared-but-unprobed endpoint on a ready capability. Both are now
  printed; `deployment.md` states that `ready` with a declared endpoint means
  locally routable, not reachable, that `--strict` still fails on `degraded`,
  and that a reachability gate needs `--strict --probe-endpoints`.
- The Fish Audio no-network test passed even with the opt-in disabled, because
  the runtime swallows exceptions raised inside a provider self-check. It now
  counts `urlopen` calls and asserts the unprobed endpoint probe.
- Full suite 213 passed, 14 skipped after six added regression tests (207
  before them); `release_check.py --require-artifacts` and `git diff --check`
  pass; `doctor` and `doctor --json` run in ~1.2s.
- Timing was re-measured with a simulated blackholed endpoint (patched
  `urlopen` sleeping 3s) rather than the original host: eight remote
  capabilities give 0 HTTP calls and 0.08s for `doctor` and 0.06s for
  `readiness` on the default path, against 10 calls and 30.1s with
  `--probe-endpoints`. The 0.14s/24.6s figures above were not reproduced.

## Readiness Probing and Manifest Isolation

Making endpoint probing opt-in everywhere also disarmed the HTTP readiness
route. The two paths are now split by what they are for.

- `specialist doctor` is unchanged: unprobed by default, `--probe-endpoints`
  opt-in, and the Python `readiness(probe_endpoints=False)` default still
  contacts nothing.
- `/ready` and `/v1/ready` call `readiness(probe_endpoints=True)`. A readiness
  route exists to test reachability, so an offline node or a dead Fish Audio
  server makes those capabilities `unavailable` again.
- The cost is bounded rather than per capability. Providers that contact a
  network endpoint now declare that URL as data (`doctor_endpoint`), and the
  readiness path probes each distinct URL once per call through a shared
  probe cache, with the timeout as a parameter
  (`READINESS_ENDPOINT_TIMEOUT = 1.0`) instead of a second hardcoded constant.
  The same cache and budget cover endpoint-kind requirement probes.
- `/studio` keeps the unprobed snapshot: it is a dashboard view, not a traffic
  gate. `/health` is static and `/metrics` does not call readiness.
- `_provider_requirements` no longer wraps the whole catalog in a bare except.
  `ProviderCatalog.scan()` loads each manifest independently and returns the
  failures, so a malformed third-party manifest drops only its own
  prerequisites and is named in the `warnings` list of both `doctor` and
  `readiness` (readiness now carries `warnings` and `probed_endpoints`).

### Verification

Measured on this host in the repository virtualenv.

- Full suite 219 passed, 14 skipped (213 before the six added tests); the
  pre-existing `test_environment` return-value warning remains.
- `release_check.py --require-artifacts` and `git diff --check` pass.
- `specialist doctor` 1.30s and `specialist doctor --json` 1.17s; both assert
  zero `urlopen` calls with an offline node registered in the home.
- Simulated blackholed endpoint (patched `urlopen` sleeping for the requested
  timeout), one node serving eight capabilities: `readiness()` default 0 calls
  / 0.08s; `/ready` path `readiness(probe_endpoints=True)` 2 calls (the node
  once plus the Fish Audio server once) / 2.07s; `doctor()` default 0 calls /
  0.07s; `doctor(probe_endpoints=True)` 10 calls / 27.11s.
- `/ready` over a real HTTP server returns 503 with the node pointed at a
  closed port and 200 against a live health server, with
  `check.endpoint_probe.status` `unreachable` / `reachable`.
- Four capabilities on one endpoint produce exactly one probe at the 1s budget
  (asserted on call count and per-call timeout, not wall time).
- A `{ this is not json` manifest in the catalog is skipped by itself: the
  sibling manifest's requirement and the builtin whisper.cpp requirements still
  evaluate, and the warning naming the file appears in `doctor` and
  `readiness`.

`docs/deployment.md` now describes the split and the (distinct endpoints x 1s)
worst-case bound. Not addressed here and still tracked separately: the
`backend == "builtin-fallback"` magic string and the runtime-lifetime caching
of `_requirement_index`. Demo/slides reconstruction, unified capability
workspaces and native playback/recording remain open. No commit, no push.

### Check Pass (readiness probing)

Re-verified independently; one defect was found and fixed in place, plus two
smaller corrections.

- The bounded readiness probe replaced each provider's health predicate with
  bare HTTP success (any status 200-499, body ignored). Reproduced against a
  real server: a node answering `200 {"status": "degraded"}` made `/ready`
  return 200 `ready` while `RemoteNodeProvider.doctor` on the same node says
  `not ready` - reachability had been silently promoted to health. Providers
  now declare the predicate as data beside the URL (`expect`: status codes, a
  JSON field and the accepted values), matching `RemoteNodeProvider.doctor`
  (200 and `status == ok`) and `FishAudioClient.health` (200, JSON,
  `status` in ok/ready/healthy). The same node now yields 503 with
  `endpoint_probe.status` `unhealthy`, distinct from `unreachable`, and error
  code `endpoint_unhealthy`.
- The probe cache was keyed by URL alone, so two providers sharing a URL with
  different credentials or a different predicate would read each other's
  verdict. The key is now (URL, digest of headers and predicate); the digest,
  not the credential, is what is stored, and `probed_endpoints` reports URLs
  only. Asserted: one URL with two tokens costs two probes and the repeated
  token is cached; no token appears in `doctor`/`readiness` JSON.
- `/studio` stays unprobed but no longer disagrees silently: the snapshot
  carries `health.endpoints_probed: false` and points at `/ready`.
- Measured here, not restated: with one offline node,
  `readiness(probe_endpoints=True)` issues 1 HTTP call in 1.06s and the default
  path 0 calls in 0.08s; `doctor()` default 0 calls. The implementer's
  8-capability figures (2 calls / 2.07s and 10 calls / 27.11s) were not
  reproducible on this host, which routes 2 capabilities to endpoint-probing
  providers; `deployment.md` now states the asserted dedupe and the serial
  (distinct endpoints x 1s) bound instead.
- Full suite 225 passed, 14 skipped (219 before the six added tests); the
  pre-existing `test_environment` return-value warning remains.
  `release_check.py --require-artifacts` and `git diff --check` pass.
  `specialist doctor` 1.59s with zero HTTP calls.

## Package E2E Scope Assertion (CI red on main)

`package-e2e` failed on `4d9e543` and `d2cb4b3` with `66 != 56`:
`tests/e2e/test_package_e2e.py` compared the combined `specialist capabilities`
output against the Core-only baseline. Verified on this host: the registry has
66 entries, 56 flagged `core`, and the 10 non-core entries are exactly
`MUSIC_CAPABILITIES`; no Core name carries the `music.` prefix.

The count was not relaxed to 66. The scopes are now asserted separately using
the `core` boolean that `registry_snapshot` already emits per capability, which
is derived from `CORE_CAPABILITIES` (ADR-003 freeze) rather than from the
`music.` prefix - the prefix is a naming convention, the flag is the registered
scope, and the installed wheel reports it without importing the checkout. The
E2E now asserts Core is exactly 56 with no `music.` member, the pack is exactly
10 with no non-`music.` member, and the two partition the whole list; the
`human.pose` / `speech.diarize` / ... membership assertions are unchanged.
Literal counts are kept so adding to either scope fails the gate until the
decision is deliberate.

`tests/test_core_scope.py` gained the same partition guard at unit level, since
the E2E only runs under `SPECIALIST_RUN_PACKAGE_E2E=1`: registry minus Core
equals `MUSIC_CAPABILITIES` (10), totals add up, and every snapshot `core` flag
agrees. Negative check: dropping `music.generate` from `MUSIC_CAPABILITIES`
fails that test with the name in the message; the file was restored.

Every other hardcoded 56 is `assertGreaterEqual` against a combined list
(`test_production`, `test_server`, `test_cli`, `test_cli_e2e`, `test_http_e2e`,
`test_mcp_e2e`), which cannot drift into this failure and was left alone.
`docs/core-scope.md`, `docs/architecture.md`, `docs/music.md`, `README.md` and
`README.zh-CN.md` state 56 for Core with Music explicitly outside it, which is
still accurate, so no documentation was changed and the uncommitted README edits
were not touched.

### Verification

- `SPECIALIST_RUN_PACKAGE_E2E=1 python -m unittest discover -s tests/e2e -p
  test_package_e2e.py -v`: 1 test, OK in 15.2s (uv build path; python-build is
  not installed in this virtualenv).
- `python -m pytest tests -q`: 226 passed, 14 skipped, 1 warning (225 before the
  added test); the pre-existing `test_environment` return-value warning remains.
- `python scripts/release_check.py --require-artifacts`: passed.
  `--require-artifacts --tag v1.1.0`: passed. `--tag v1.1.1`: exits 1 with
  "release tag 'v1.1.1' does not match project version 'v1.1.0'" - the version
  bump is the release commit's, not made here.
- `uv lock --check --no-config --default-index https://pypi.org/simple`:
  resolved 3 packages, up to date.
- `uv build`: `specialist_os-1.1.0-py3-none-any.whl` and
  `specialist_os-1.1.0.tar.gz` built into a scratch directory.
- `git diff --check`: clean. No commit, no tag, no push.

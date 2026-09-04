# Deployment

Specialist Runtime is intended to run as a local service next to an agent. The
recommended production process is:

```bash
SPECIALIST_API_TOKEN=$(openssl rand -hex 32) \
  specialist serve --host 127.0.0.1 --port 8741
```

Keep the service loopback-only unless a private network policy and token are in
place. `/health` is a liveness check; `/ready` reports the runtime state;
`/metrics` exposes local counters. The server starts isolated workers lazily,
one per capability, and shuts them down on SIGINT.

`/ready` describes whether the running service can accept requests. Use
`specialist doctor --strict --json` as the stronger release gate: it also
requires every configured capability to have a ready provider/model rather
than silently relying on fallback behavior.

For launchd/systemd, run the installed `specialist` executable directly with a
dedicated `SPECIALIST_HOME`, a restrictive filesystem account, and an explicit
token in the service manager's secret store. Do not put model or input files in
the repository. Set cache cleanup policy with:

```bash
specialist models clean --max-age-hours 168 --max-entries 5000
```

Model downloads must provide a SHA256 checksum. Failed or interrupted
downloads are removed before an installation marker is committed.

Fish Audio is the exception by design: its `server`-managed registry model is
owned by an operator-managed Fish HTTP service rather than downloaded by Core.
Configure `SPECIALIST_FISH_AUDIO_URL`, optionally
`SPECIALIST_FISH_AUDIO_COMMAND`, and verify `/v1/health` before enabling
`speech.synthesize` or `speech.clone_voice`. The provider remains isolated and
uses a single request per model instance.

For a local Fish Speech S2 service, start the upstream server from its checked-out
Fish Speech release:

```bash
python /path/to/fish-speech/tools/api_server.py --listen 127.0.0.1:8080
```

Use the absolute path to the checked-out Fish Speech release in
`SPECIALIST_FISH_AUDIO_COMMAND` when Specialist OS manages this process.

Then point Specialist OS at the service and run the readiness check:

```bash
export SPECIALIST_FISH_AUDIO_URL=http://127.0.0.1:8080
specialist --backend real doctor --strict --json
```

The release contains a CycloneDX SBOM (`sbom.cdx.json`) and GitHub build
provenance attestation. Keep both with the deployed package record and verify
the published `SHA256SUMS` file before promotion.

Optional providers do not get permission to invoke their upstream weight
downloaders by default. Install a verified artifact first, or make the trust
decision explicit with `--allow-unverified-models` (or
`SPECIALIST_ALLOW_UNVERIFIED_MODELS=1`) in a controlled environment.

Use the real backend and isolated environments for a production install:

```bash
specialist --backend real --with-dependencies install vision
specialist --backend real --with-dependencies install audio
specialist --backend auto --with-dependencies doctor --strict --json
```

The isolated worker prepends its environment's `bin` directory to `PATH`, so
console entry points such as `mineru` are resolved from the same environment as
their Python modules. Set `SPECIALIST_WHISPER_BINARY`,
`SPECIALIST_MINERU_COMMAND`, or `SPECIALIST_OMNIPARSER_COMMAND` when a host
binary or a reviewed wrapper lives outside the default name. The default
MinerU command for version 3.4.5 is `mineru`.

MinerU's published wheel is verified and installed into its provider
environment, but its pipeline model repository is a separate upstream snapshot.
Provision those models locally and configure MinerU before enabling
`document.parse` by setting `SPECIALIST_MINERU_MODEL_DIR`; verified Specialist
workers set `MINERU_MODEL_SOURCE=local` to prevent an accidental remote
download. OmniParser is similarly exposed as a
JSON CLI contract and receives the verified bundle path through
`OMNIPARSER_MODEL_DIR` and `SPECIALIST_MODEL_ARTIFACT`.

Use `specialist models list`, `specialist doctor --json` and
`specialist doctor --strict --json` in deployment health checks. The strict
variant exits non-zero when any capability is unavailable, unconfigured or has
a corrupt/error model state. A tampered artifact is reported as `corrupt` and
will not be silently replaced.

Before promoting a release, run the process-boundary E2E suite from a clean
checkout. It uses fallback providers and temporary state, so it does not
download model weights:

```bash
python -m unittest discover -s tests/e2e -v
```

The release-path check builds a wheel, installs it into a clean virtual
environment, and runs the CLI without the source checkout on `PYTHONPATH`:

```bash
python -m pip install build setuptools
SPECIALIST_RUN_PACKAGE_E2E=1 python -m unittest discover -s tests/e2e -p test_package_e2e.py -v
```

Release tags are guarded by `.github/workflows/release.yml`. The tag must match
the project version (`v<version>`). For downloadable models,
`scripts/release_check.py --require-artifacts` requires a paired HTTPS URL and
SHA256; operator-owned `server` models intentionally carry no download
artifact. Multi-file providers use an atomic manifest that records and verifies
every file before loading.

Reference service-manager templates are provided at
`deploy/systemd/specialist.service` and
`deploy/launchd/com.specialist.runtime.plist`. Replace paths and secrets for
the target host; never commit a real API token.

To explicitly repair provider environments, run:

```bash
specialist --backend auto --with-dependencies doctor --fix
```

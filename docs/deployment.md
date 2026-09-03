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

Optional providers do not get permission to invoke their upstream weight
downloaders by default. Install a verified artifact first, or make the trust
decision explicit with `--allow-unverified-models` (or
`SPECIALIST_ALLOW_UNVERIFIED_MODELS=1`) in a controlled environment.

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
the project version (`v<version>`), and
`scripts/release_check.py --require-artifacts` requires every model entry to
carry a paired URL and SHA256. The current registry intentionally has no
unverified production artifacts, so adding real provider weights and their
license/provenance records is a prerequisite for a publishable release.

Reference service-manager templates are provided at
`deploy/systemd/specialist.service` and
`deploy/launchd/com.specialist.runtime.plist`. Replace paths and secrets for
the target host; never commit a real API token.

To explicitly repair provider environments, run:

```bash
specialist --backend auto --with-dependencies doctor --fix
```

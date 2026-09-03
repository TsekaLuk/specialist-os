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

Use `specialist models list` and `specialist doctor --json` in deployment
health checks. A tampered artifact is reported as `corrupt` and will not be
silently replaced.

To explicitly repair provider environments, run:

```bash
specialist --backend auto --with-dependencies doctor --fix
```

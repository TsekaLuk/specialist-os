# Security policy

Specialist OS treats local inputs as untrusted. The runtime enforces a
512 MiB input limit, JSON request limits, provider timeouts, worker output
limits, optional POSIX memory/CPU limits, and atomic artifact verification.

Keep the HTTP server bound to loopback unless a token is configured. Do not
expose it directly to the public internet. Set `SPECIALIST_API_TOKEN` for any
non-loopback bind.

Model artifacts are installed atomically and must carry a SHA256 digest.
Optional providers are fail-closed unless `--allow-unverified-models` is
explicitly enabled. Treat that flag as a supply-chain trust decision.

Please report vulnerabilities privately to the repository maintainers before
opening a public issue. Include the runtime version, platform, provider, a
minimal reproduction, and whether the isolated worker mode was enabled.

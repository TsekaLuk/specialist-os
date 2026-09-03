# Contributing

Small, focused changes are welcome. Keep capability names and result envelopes
backward compatible. A new provider should implement the protocol in
`specialist/providers/base.py`, document its model and license metadata, and
include a fixture-based test that works without network access.

Registry entries must include a provenance URL, exactly one recommended model,
platform/device constraints, and either both artifact URL plus SHA256 or neither
until a digest is independently verified. Do not add implicit network downloads
to the default path.

Run the local checks before opening a pull request:

```bash
python -m unittest discover -s tests -v
python -m unittest discover -s tests/e2e -v
cargo test --manifest-path rust-core/Cargo.toml
```

The E2E tests exercise real subprocess and transport boundaries with temporary
homes and fallback providers. They do not download model weights. The optional
wheel-installation E2E can be run after installing `build`:

```bash
python -m pip install build setuptools
SPECIALIST_RUN_PACKAGE_E2E=1 python -m unittest discover -s tests/e2e -p test_package_e2e.py -v
```

Provider credentials, verified model artifacts and hardware-specific coverage
should be supplied by a separate integration job rather than committed as
test fixtures.

Release metadata can be checked locally with:

```bash
python scripts/release_check.py
python scripts/release_check.py --require-artifacts
```

The strict form is expected to fail until every production model has an
audited, downloadable artifact and checksum.

Do not add telemetry, remote inference, or heavyweight dependencies to the core
runtime without an explicit design discussion.

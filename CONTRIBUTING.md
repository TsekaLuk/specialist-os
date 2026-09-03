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
cargo test --manifest-path rust-core/Cargo.toml
```

Do not add telemetry, remote inference, or heavyweight dependencies to the core
runtime without an explicit design discussion.

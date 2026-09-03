# Architecture

The runtime has four small layers:

1. `specialist.registry` loads and validates the checked-in model registry,
   including provider provenance, model versions, platform/device support and
   license metadata.
2. `specialist.runtime` resolves a capability, applies safety limits, lazily installs its provider, and writes the unified result envelope to the local cache.
3. Providers implement `install`, `doctor`, `load`, `infer`, and `unload` behind a narrow protocol. Built-ins can run in a persistent isolated JSON Lines worker with wall-clock, output-size, and POSIX resource limits; native providers can use the same transport. `ProviderEnvironmentManager` creates a separate uv/venv environment per provider when explicitly requested.
4. CLI, HTTP, MCP, and the Python SDK are adapters over the same runtime object.

The envelope and capability payload contracts are published in
`schemas/result-envelope.schema.json` and
`schemas/capability-results.schema.json`. Runtime validation covers the same
required fields without requiring a JSON Schema dependency.

The optional `rust-core` crate contains deterministic primitives that should be
shared by future native workers. It can be compiled as a PyO3 extension, but no
core path requires the extension to be present. Runtime events are written to a
local rotating JSONL log and no telemetry leaves the machine.

## Adding a provider

Implement the protocol in `specialist/providers/base.py`, add a `CapabilitySpec`
to `specialist/registry.py`, then pass the provider via
`SpecialistRuntime(provider_overrides={"capability.name": provider})` while
integrating. Keep output schemas backward compatible and record upstream model
license and checksum metadata in `registry/models.yaml`.

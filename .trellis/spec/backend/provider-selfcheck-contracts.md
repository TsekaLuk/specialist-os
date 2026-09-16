# Provider Self-Check Contracts

## 1. Scope / Trigger

Provider prerequisite declaration, the `doctor` / `readiness` reports, and the
HTTP readiness gate. Triggered by any change to `specialist/requirements.py`,
`specialist/provider_manifest.py`, `ProviderAdapter`, `SpecialistRuntime.doctor`,
`SpecialistRuntime.readiness`, or the `/ready` handler. A new provider that has
any external prerequisite is in scope.

## 2. Signatures

```python
ProviderRequirement(kind, name, purpose, optional=False, group=None)
probe_requirement(requirement, *, environ=None, endpoint_timeout=None, probe_cache=None)
evaluate_requirements(requirements, *, environ=None, endpoint_timeout=None, probe_cache=None)
probe_endpoint_url(url, *, timeout, headers, expect, probe_cache)

ProviderAdapter.doctor_probes_endpoint: bool = False
ProviderAdapter.doctor_endpoint() -> dict | None   # {"url", "headers", "expect"}
ProviderAdapter.doctor_local(hardware) -> dict     # no network

SpecialistRuntime.doctor(fix=False, *, probe_endpoints=False)
SpecialistRuntime.readiness(*, probe_endpoints=False,
                            endpoint_timeout=READINESS_ENDPOINT_TIMEOUT)
```

## 3. Contracts

`kind` is one of `binary` | `env` | `file` | `endpoint`. `purpose` is a human
string naming what the prerequisite is for; it is printed, so write it for an
operator, not a maintainer.

`group` marks interchangeable SOURCES of one requirement. A group is satisfied
when ANY member is satisfied. A credential readable from either an environment
variable or a credential file is one requirement with two sources; reporting the
unused source as missing raises a false alarm on a capability that works. A group
counts as optional only when EVERY member is optional, so a mixed group can still
degrade a capability.

`ok` is TRI-STATE: `True` satisfied, `False` missing, `None` declared but not
probed. `None` must never be coerced to a bool. Compare with `is True` / `is None`;
`if not ok` silently turns "not checked" into "missing".

`doctor_endpoint()` carries the health PREDICATE as data next to the URL:
`expect` declares the accepted HTTP status, the JSON field to read, and the
accepted values. The predicate mirrors the provider's own health contract —
`RemoteNodeProvider` requires 200 plus `status == "ok"`, `FishAudioClient.health`
requires 200 plus JSON with `status` in `{ok, ready, healthy}`.

Requirements are probed in the PROVIDER's environment, not the parent process
environment. `_worker_provider` builds `worker_env["PATH"] = <provider venv bin> +
os.environ["PATH"]`, so a console script installed in an isolated provider
environment is invisible to the parent. An injected environment is authoritative:
do not fall back to the real `PATH` when it lacks one.

Probe cache keys are `(url, sha256(headers + expect)[:16])`. The cache is a local
variable of one `readiness()` call, never stored on the runtime.

Credentials travel as data in `headers` but must never reach serialized output.
Only `url` is serialized; the header digest is a fingerprint, not a value.

Manifest parsing isolates failures per file: `ProviderCatalog.scan()` returns
`(manifests, errors)` and a malformed manifest drops only its own requirements,
surfacing a warning naming the path. A bare `except` around a whole catalog read
reports every capability as satisfied because nothing was read — the inverse of a
false alarm, and worse.

## 4. Validation & Error Matrix

| Condition | Result |
| --- | --- |
| Non-optional group with no satisfied member | capability `degraded`, group named in output |
| Group with any satisfied member | no gap reported |
| Group whose members are all `optional` | stays `ready` |
| Mixed optional/non-optional group, none satisfied | `degraded` |
| `endpoint` kind on an interactive path | `ok=None`, reported as not probed |
| Endpoint unreachable on the gate path | `endpoint_probe.status=unreachable`, 503 |
| Endpoint answers but fails its predicate | `endpoint_probe.status=unhealthy`, `error.code=endpoint_unhealthy`, 503 |
| Malformed provider manifest | that provider yields `()`, warning names the path |

Status levels: `ready`, `degraded`, `not installed`, `error`, `corrupt`,
`unavailable`. `degraded` means installed and routable with a non-optional
requirement group unmet — the call is ACCEPTED and fails at execution. That is a
different operator action from not-installed and from load-failed. `degraded` is
not `ready`, so `doctor --strict` exits non-zero.

## 5. Good/Base/Bad Cases

- Good: a token readable from `HF_TOKEN` or `~/.cache/huggingface/token`, declared
  as one `group` with two members; one present, no gap reported.
- Base: `specialist doctor` on a host with a registered but offline remote node —
  0 HTTP calls, report returns immediately, the endpoint is listed as not probed.
- Bad: a node answering `200 {"status": "degraded"}` read as healthy because the
  probe only checked the HTTP status and never read the body.

## 6. Tests Required

- Group satisfied by exactly one member reports no gap; optional-only missing
  stays `ready`; mixed group degrades.
- `specialist doctor` and `doctor --json` with an offline node registered: assert
  `urlopen` CALL COUNT is zero, not wall time. A patched probe that raises is
  swallowed by the caller's `except Exception`, so an exception-based assertion
  passes even when the probe ran — count calls instead.
- Requirement probing uses the provider environment: mutation test, reverting the
  injected `environ` must fail the test.
- Predicate parity: probe verdict equals the provider's own `doctor()` verdict for
  reachable-healthy, reachable-unhealthy and unreachable.
- Dedupe: N capabilities on one endpoint cost exactly 1 probe at the gate timeout;
  one URL with two different tokens costs 2.
- No credential in output: `json.dumps` the whole `doctor()` and `readiness()`
  report and assert the token is absent. Do not verify by reading the constructor.
- Core scope partition (see section 8).

## 7. Wrong vs Correct

### Wrong

```python
# Generic reachability. A 404, a 401, or a 200 with a sick body all read as ready.
def probe(url, timeout):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return 200 <= response.status < 500
```

### Correct

```python
# The provider's own predicate travels with the URL.
def doctor_endpoint(self):
    return {"url": f"{self.endpoint}/health",
            "headers": self._headers(),
            "expect": {"status": 200, "json_field": "status", "accept": ("ok",)}}
```

## 8. Scope Freeze

The registry `core` boolean, derived from `CORE_CAPABILITIES` in
`specialist/core.py` (ADR-003), is authoritative for Core membership. The
`music.` name prefix is a naming convention and must not be used as the
classifier — the installed wheel reports `core` in its own CLI JSON, so the
package E2E stays checkout-free.

CI asserts Core and the Music pack as SEPARATE literal counts that partition the
full capability list. A flat `assertEqual(len(all), 56)` breaks the moment a pack
ships and, if repaired by bumping the number, silently deletes the freeze. Adding
to either scope must fail the gate until the change is deliberate.

## 9. Known Gaps

- The `builtin-fallback` exemption that skips requirement evaluation is an
  undocumented magic string inside a provider's returned dict
  (`BuiltinProvider.doctor`). A future adapter that copies that dict silently
  loses its prerequisite check. A `skips_requirements = True` class attribute
  would be a real contract.
- `_requirement_index` is cached for the runtime's lifetime, so a capability
  installed after startup needs a restart before its requirements are read.

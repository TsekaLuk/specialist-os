"""Declarative provider prerequisites and their probe policy.

Requirements are plain data so a capability can be inspected before any
provider code is imported or executed, exactly like the provider manifest they
travel with. Requirements that share a ``group`` are interchangeable sources of
the same prerequisite: the group is satisfied when any member is satisfied, so
a credential readable from either an environment variable or a credential file
is reported once and never as a missing source on a capability that works.

Probing is deliberately cheap and local: ``binary`` resolves against PATH,
``env`` reads the environment and ``file`` checks existence. An ``endpoint`` is
never contacted on the default path; it is reported as declared-but-unprobed
(``ok`` is ``None``) and the first real call surfaces reachability. Blocking a
self-check on an unreachable host is worse than admitting it was not checked.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
from typing import Any, Iterable, Mapping

REQUIREMENT_KINDS = ("binary", "env", "file", "endpoint")

# Timeout used when an operator explicitly asks for endpoint probes. Callers on
# a latency-sensitive path (the HTTP readiness probe) pass a shorter value.
DEFAULT_ENDPOINT_TIMEOUT = 3.0


class RequirementError(ValueError):
    """Raised when a declared requirement is malformed."""


@dataclass(frozen=True)
class ProviderRequirement:
    kind: str
    name: str
    purpose: str = ""
    optional: bool = False
    group: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in REQUIREMENT_KINDS:
            raise RequirementError(f"requirement kind must be one of {list(REQUIREMENT_KINDS)}")
        if not isinstance(self.name, str) or not self.name.strip():
            raise RequirementError("requirement name must be a non-empty string")

    @property
    def group_key(self) -> str:
        """Label used to collapse interchangeable sources into one requirement."""
        return self.group or f"{self.kind}:{self.name}"

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProviderRequirement":
        if not isinstance(value, Mapping):
            raise RequirementError("requirement must be an object")
        unknown = set(value).difference({"kind", "name", "purpose", "optional", "group"})
        if unknown:
            raise RequirementError(f"requirement has unknown keys: {sorted(unknown)}")
        optional = value.get("optional", False)
        if not isinstance(optional, bool):
            raise RequirementError("requirement optional must be boolean")
        group = value.get("group")
        if group is not None and (not isinstance(group, str) or not group.strip()):
            raise RequirementError("requirement group must be a non-empty string when present")
        purpose = value.get("purpose", "")
        if not isinstance(purpose, str):
            raise RequirementError("requirement purpose must be a string")
        kind = value.get("kind")
        name = value.get("name")
        if not isinstance(kind, str) or not isinstance(name, str):
            raise RequirementError("requirement kind and name must be strings")
        return cls(kind.strip(), name.strip(), purpose.strip(), optional, group.strip() if isinstance(group, str) else None)

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {"kind": self.kind, "name": self.name, "purpose": self.purpose, "optional": self.optional}
        if self.group:
            value["group"] = self.group
        return value


def parse_requirements(value: Any) -> tuple[ProviderRequirement, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise RequirementError("requirements must be a list")
    return tuple(item if isinstance(item, ProviderRequirement) else ProviderRequirement.from_dict(item) for item in value)


def probe_requirement(requirement: ProviderRequirement, *, probe_endpoints: bool = False, environ: Mapping[str, str] | None = None,
                      endpoint_timeout: float = DEFAULT_ENDPOINT_TIMEOUT, probe_cache: dict[tuple[str, str], tuple[bool, str, str]] | None = None) -> dict[str, Any]:
    """Probe one requirement locally.

    ``ok`` is ``True`` when satisfied, ``False`` when missing and ``None`` when
    the requirement was declared but deliberately not probed. ``probe_cache``
    makes one endpoint cost one request per call even when several capabilities
    declare the same URL.
    """
    environment = os.environ if environ is None else environ
    value = requirement.to_dict()
    value["group_key"] = requirement.group_key
    ok: bool | None = None
    detail: str | None = None
    if requirement.kind == "binary":
        # An injected environment is authoritative: falling back to the real
        # PATH would make an isolated probe depend on the calling host.
        resolved = shutil.which(requirement.name) if environ is None else shutil.which(requirement.name, path=environment.get("PATH", ""))
        ok = resolved is not None
        detail = resolved or f"'{requirement.name}' was not found on PATH"
    elif requirement.kind == "env":
        ok = bool((environment.get(requirement.name) or "").strip())
        detail = "set" if ok else f"environment variable {requirement.name} is not set"
    elif requirement.kind == "file":
        path = Path(os.path.expandvars(requirement.name)).expanduser()
        ok = path.exists()
        detail = str(path) if ok else f"{path} does not exist"
    else:  # endpoint
        if probe_endpoints:
            ok, detail = _probe_endpoint(requirement, environment, timeout=endpoint_timeout, probe_cache=probe_cache)
        else:
            ok = None
            detail = "declared but not probed; self-check never contacts an endpoint by default"
    value["ok"] = ok
    value["detail"] = detail
    value["probed"] = ok is not None
    return value


def _probe_endpoint(requirement: ProviderRequirement, environment: Mapping[str, str], *, timeout: float = DEFAULT_ENDPOINT_TIMEOUT,
                    probe_cache: dict[tuple[str, str], tuple[bool, str, str]] | None = None) -> tuple[bool, str]:
    """Contact an endpoint. Only reachable through an explicit operator opt-in."""
    target = requirement.name
    if not target.startswith(("http://", "https://")):
        target = (environment.get(target) or "").strip()
        if not target:
            return False, f"no endpoint is configured for {requirement.name}"
    ok, _state, detail = probe_endpoint_url(target, timeout=timeout, probe_cache=probe_cache)
    return ok, detail


#: Largest health body read while evaluating a declared predicate. A health
#: document is small; anything larger is not worth holding in a readiness path.
MAX_HEALTH_BODY_BYTES = 64 * 1024


def probe_cache_key(url: str, headers: Mapping[str, str] | None = None, expect: Mapping[str, Any] | None = None) -> tuple[str, str]:
    """Cache identity for one probe.

    Two providers can point at the same URL with different credentials or a
    different health predicate; sharing a cached verdict between them would
    report one provider's result as the other's. The credential itself never
    becomes part of the key - only a digest of it - so the key can be handled
    and, with the URL taken out of it, reported without leaking a token.
    """
    import hashlib

    material = json.dumps({"headers": {str(key).lower(): str(value) for key, value in sorted((headers or {}).items())},
                           "expect": _expectation(expect)}, sort_keys=True, ensure_ascii=True)
    return url, hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def _expectation(expect: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalize a declared health predicate into comparable data."""
    if not isinstance(expect, Mapping):
        return {}
    status = expect.get("status")
    statuses = sorted({int(item) for item in (status if isinstance(status, (list, tuple, set)) else [status] if status is not None else [])})
    accept = expect.get("accept")
    values = sorted({str(item).lower() for item in (accept if isinstance(accept, (list, tuple, set)) else [accept] if accept is not None else [])})
    field = expect.get("json_field")
    return {"status": statuses, "json_field": field if isinstance(field, str) and field.strip() else None, "accept": values}


def _evaluate_health(url: str, status_code: int, body: bytes, expect: dict[str, Any]) -> tuple[bool, str, str]:
    """Apply the provider's own health predicate to one response.

    Reachability is not health. A node that answers 200 while reporting itself
    unhealthy must not open the traffic gate, so the predicate the provider
    used in its own ``doctor`` is carried here as data and applied verbatim.
    """
    allowed = expect.get("status") or []
    if allowed and status_code not in allowed:
        return False, "unhealthy", f"{url} responded with {status_code}, expected {' or '.join(str(item) for item in allowed)}"
    if not allowed and not (200 <= status_code < 500):
        return False, "unhealthy", f"{url} responded with {status_code}"
    field = expect.get("json_field")
    if not field:
        return True, "reachable", f"{url} responded with {status_code}"
    try:
        payload = json.loads(body or b"{}")
    except ValueError:
        return False, "unhealthy", f"{url} responded with {status_code} but the body is not JSON"
    if not isinstance(payload, Mapping):
        return False, "unhealthy", f"{url} responded with {status_code} but the body is not a JSON object"
    reported = str(payload.get(field, ""))
    accept = expect.get("accept") or []
    if accept and reported.lower() not in accept:
        # Only the reported status word is echoed; the rest of the body may
        # carry operational detail that does not belong in a readiness report.
        return False, "unhealthy", f"{url} is reachable but reports {field}={reported[:64] or 'missing'!r}, expected {' or '.join(accept)}"
    return True, "reachable", f"{url} responded with {status_code} and {field}={reported[:64]!r}"


def probe_endpoint_url(url: str, *, timeout: float = DEFAULT_ENDPOINT_TIMEOUT, headers: Mapping[str, str] | None = None,
                       expect: Mapping[str, Any] | None = None,
                       probe_cache: dict[tuple[str, str], tuple[bool, str, str]] | None = None) -> tuple[bool, str, str]:
    """Contact one URL at most once per ``probe_cache``.

    Several capabilities routinely point at the same node, so an unreachable
    host costs one timeout per report rather than one per capability. ``expect``
    carries the provider's own health predicate (status codes, a JSON field and
    the values it accepts) so a bounded probe keeps the provider's semantics
    instead of downgrading them to "the socket answered".

    Returns ``(ok, state, detail)`` where ``state`` separates ``unreachable``
    (no answer) from ``unhealthy`` (an answer that fails the predicate); the two
    call for different operator action.
    """
    import urllib.error
    import urllib.request

    expectation = _expectation(expect)
    key = probe_cache_key(url, headers, expect)
    if probe_cache is not None and key in probe_cache:
        return probe_cache[key]
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=dict(headers or {}), method="GET"), timeout=timeout) as response:
            body = response.read(MAX_HEALTH_BODY_BYTES) if expectation.get("json_field") else b""
            result = _evaluate_health(url, int(response.status or 0), body, expectation)
    except urllib.error.HTTPError as exc:
        # An HTTP error status is an answer, so the predicate still decides:
        # a 401 from an authenticated node is a real failure, not a timeout.
        try:
            body = exc.read(MAX_HEALTH_BODY_BYTES) if expectation.get("json_field") else b""
        except OSError:
            body = b""
        result = _evaluate_health(url, int(exc.code or 0), body, expectation)
    except (OSError, urllib.error.URLError, ValueError) as exc:
        result = (False, "unreachable", f"{url} is unreachable: {exc}")
    if probe_cache is not None:
        probe_cache[key] = result
    return result


def evaluate_requirements(requirements: Iterable[ProviderRequirement], *, probe_endpoints: bool = False, environ: Mapping[str, str] | None = None,
                          endpoint_timeout: float = DEFAULT_ENDPOINT_TIMEOUT, probe_cache: dict[tuple[str, str], tuple[bool, str, str]] | None = None) -> dict[str, Any]:
    """Probe requirements and collapse interchangeable sources into groups."""
    probes = [probe_requirement(item, probe_endpoints=probe_endpoints, environ=environ, endpoint_timeout=endpoint_timeout, probe_cache=probe_cache) for item in requirements]
    groups: dict[str, dict[str, Any]] = {}
    for probe in probes:
        group = groups.setdefault(probe["group_key"], {"group": probe["group_key"], "label": probe.get("group"), "optional": True, "sources": [], "purpose": ""})
        group["sources"].append(probe)
        group["optional"] = group["optional"] and probe["optional"]
        if probe["purpose"] and not group["purpose"]:
            group["purpose"] = probe["purpose"]
    values = []
    for group in groups.values():
        results = [item["ok"] for item in group["sources"]]
        if any(result is True for result in results):
            status = "satisfied"
        elif all(result is None for result in results):
            status = "unprobed"
        elif any(result is None for result in results):
            # A satisfied local source would have short-circuited above, so the
            # group still depends on something that was deliberately not probed.
            status = "unprobed"
        else:
            status = "missing"
        group["status"] = status
        values.append(group)
    unmet = [item for item in values if item["status"] == "missing" and not item["optional"]]
    return {
        "requirements": probes,
        "groups": values,
        "unmet": unmet,
        "unmet_optional": [item for item in values if item["status"] == "missing" and item["optional"]],
        "unprobed": [item for item in values if item["status"] == "unprobed"],
        "satisfied": all(item["status"] != "missing" or item["optional"] for item in values),
    }


def describe_group(group: Mapping[str, Any]) -> str:
    """One-line human description of an unmet requirement group."""
    sources = " or ".join(f"{item['kind']} {item['name']}" for item in group.get("sources", []))
    label = group.get("label")
    text = f"{label} ({sources})" if label else sources
    purpose = group.get("purpose")
    return f"{text} - {purpose}" if purpose else text

"""Capability orchestration, lazy installation and result caching."""

from __future__ import annotations

import time
import threading
import os
import sys
import json
from pathlib import Path
from typing import Any

from .cache import Cache
from .artifacts import ArtifactError, ArtifactStore
from .hardware import detect_hardware, recommended_model, target_id
from .models import ModelManager
from .environments import EnvironmentError, ProviderEnvironmentManager, PROVIDER_REQUIREMENTS
from .observability import EventLogger
from .providers import JsonlProcessProvider, WorkerError
from .providers.factory import provider_map
from .registry import BUNDLES, CAPABILITIES, registry_snapshot, resolve_capability
from .rust_core import rust_validate_input
from .schemas import ResultEnvelope, validate_envelope
from .observation import aggregate_confidence, build_observations, evidence_from_observations
from .policy import Policy, PolicyError
from .router import DeterministicRouter, RoutingError
from .streaming import SessionManager
from .benchmark import BenchmarkRecord, BenchmarkRegistry
from .node import NodeRegistry
from .provider_manifest import ProviderCatalog, builtin_manifests
from .remote import RemoteNodeProvider
from .packs import get_pack
from .voices import VoiceRegistry


class SpecialistRuntime:
    TIMEOUTS = {"vision.detect": 120, "vision.segment": 120, "vision.ocr": 120, "vision.depth": 300, "screen.parse": 120, "document.parse": 900, "audio.transcribe": 900, "audio.vad": 300, "speech.synthesize": 1800, "speech.clone_voice": 1800}

    def __init__(self, home=None, provider_overrides=None, isolate=False, backend="auto", with_dependencies=False, max_loaded=4, allow_unverified_models=None):
        self.cache = Cache(home)
        self.artifacts = ArtifactStore(self.cache.artifacts)
        self.voices = VoiceRegistry(self.cache.home / "voices", self.artifacts)
        self.policy = Policy.load(self.cache.home, cwd=Path.cwd())
        self.backend = backend
        self.with_dependencies = with_dependencies
        self.allow_unverified_models = bool(os.environ.get("SPECIALIST_ALLOW_UNVERIFIED_MODELS") == "1") if allow_unverified_models is None else bool(allow_unverified_models)
        self.max_loaded = max(1, int(max_loaded))
        self.providers = provider_map(backend)
        self.environments = ProviderEnvironmentManager(self.cache)
        if backend == "auto":
            # Promote only capabilities with a persisted artifact. This keeps
            # a fresh install deterministic while allowing a later process to
            # use an installed command provider such as whisper.cpp or MinerU.
            real_providers = provider_map("real")
            for name, provider in list(self.providers.items()):
                installation = self.cache.installation(name)
                if installation and installation.get("artifact_path") and name in real_providers:
                    selected = real_providers[name]
                    selected._allow_unverified_models = self.allow_unverified_models
                    self.providers[name] = selected
        if provider_overrides:
            self.providers.update(provider_overrides)
        for provider in self.providers.values():
            if hasattr(provider, "_allow_unverified_models"):
                provider._allow_unverified_models = self.allow_unverified_models
        self.isolate = bool(isolate or with_dependencies or os.environ.get("SPECIALIST_ISOLATE") == "1")
        if self.isolate:
            for name, provider in list(self.providers.items()):
                if name not in (provider_overrides or {}):
                    self.providers[name] = self._worker_provider(name, provider, sys.executable)
        self._loaded: set[str] = set()
        self._active_providers: dict[str, Any] = {}
        self._last_used: dict[str, float] = {}
        self._locks = {name: threading.RLock() for name in self.providers}
        self._metrics_lock = threading.Lock()
        self.models_manager = ModelManager(self.cache)
        self.logger = EventLogger(self.cache.home, enabled=True)
        self._metrics = {"requests_total": 0, "errors_total": 0, "cache_hits_total": 0, "latency_ms_total": 0}
        self.sessions = SessionManager(self)
        self.benchmarks = BenchmarkRegistry(self.cache.metadata / "benchmarks.json")
        self.nodes = NodeRegistry(self.cache.home / "nodes")
        self.provider_catalog = ProviderCatalog(self.cache.home / "providers")
        self._attach_remote_nodes()

        # On a subsequent process start, reuse an already-created provider
        # environment instead of silently wrapping the dependency-free
        # fallback with the host interpreter. This keeps ``doctor`` and actual
        # inference aligned after a production install.
        if self.with_dependencies and self.backend != "fallback":
            real_providers = provider_map("real")
            for name, spec in CAPABILITIES.items():
                requirements = PROVIDER_REQUIREMENTS.get(spec.optional_dependency or "", [])
                if not requirements or name in (provider_overrides or {}):
                    continue
                environment = self.environments.status(spec.provider)
                if environment.get("status") == "ready":
                    selected = real_providers[name]
                    selected._allow_unverified_models = self.allow_unverified_models
                    self.providers[name] = self._worker_provider(name, selected, environment["python"], requires_verified_artifact=True)

    def capabilities(self):
        return registry_snapshot()

    def _attach_remote_nodes(self):
        for node in self.nodes.list():
            endpoint = (node.metadata or {}).get("endpoint")
            if not isinstance(endpoint, str) or not endpoint.startswith(("http://", "https://")):
                continue
            token = None
            token_env = (node.metadata or {}).get("token_env")
            if isinstance(token_env, str) and token_env:
                token = os.environ.get(token_env)
            for capability in node.capabilities:
                if capability in CAPABILITIES:
                    key = f"{capability}@{node.node_id}"
                    self.providers.setdefault(key, RemoteNodeProvider(node.node_id, capability, endpoint, token=token, latency_ms=node.latency_ms, memory_mb=node.memory_mb))
        for key in self.providers:
            self._locks.setdefault(key, threading.RLock())

    @staticmethod
    def _model_for(spec, installation=None, hardware=None):
        if installation and installation.get("model") in {item.id for item in spec.models}:
            return installation["model"]
        return recommended_model(spec, hardware)

    def _worker_provider(self, name, provider, python, requires_verified_artifact=None):
        package_root = str(Path(__file__).resolve().parents[1])
        current_pythonpath = os.environ.get("PYTHONPATH", "")
        pythonpath = package_root if not current_pythonpath else package_root + os.pathsep + current_pythonpath
        timeout = self.TIMEOUTS.get(name, 120)
        worker_env = {
            "SPECIALIST_HOME": str(self.cache.home),
            "PYTHONPATH": pythonpath,
            "SPECIALIST_ALLOW_UNVERIFIED_MODELS": "1" if self.allow_unverified_models else "0",
        }
        # Provider selection and local model configuration happen again inside
        # the worker process. Carry the reviewed operator settings across that
        # process boundary so an isolated worker uses the same binary/model
        # directories as the parent runtime.
        for key in (
            "SPECIALIST_WHISPER_BINARY",
            "SPECIALIST_MINERU_COMMAND",
            "SPECIALIST_MINERU_MODEL_DIR",
            "SPECIALIST_OMNIPARSER_COMMAND",
            "OMNIPARSER_MODEL_DIR",
            "MINERU_TOOLS_CONFIG_JSON",
            "SPECIALIST_FISH_AUDIO_URL",
            "SPECIALIST_FISH_AUDIO_TOKEN",
            "SPECIALIST_FISH_AUDIO_COMMAND",
            "SPECIALIST_FISH_AUDIO_START_POLICY",
            "SPECIALIST_FISH_AUDIO_STARTUP_TIMEOUT",
            "SPECIALIST_PRIVACY_ALLOW_REMOTE",
        ):
            if key in os.environ:
                worker_env[key] = os.environ[key]
        # Console entry points installed in an isolated provider environment
        # live beside its Python executable. Prepend that directory so command
        # providers are resolved by both provider_map and the worker process.
        if python:
            # Do not resolve the venv's ``bin/python`` symlink: console scripts
            # live beside the logical interpreter path, not beside its system
            # Python target.
            bin_dir = str(Path(python).parent)
            worker_env["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
        artifact_required = bool(getattr(provider, "requires_verified_artifact", False) if requires_verified_artifact is None else requires_verified_artifact)
        worker_backend = "real" if self.backend == "auto" and artifact_required else self.backend
        # Model providers can reserve substantially more virtual address space
        # than their steady-state RSS. Keep the generic ceiling for small
        # providers but let heavyweight providers such as SAM2 start without
        # being killed by RLIMIT_AS before inference begins.
        provider_memory_mb = int(getattr(provider, "memory_requirement_mb", 0) or 0)
        memory_limit_bytes = max(4 * 1024**3, (provider_memory_mb + 2048) * 1024**2)
        worker_capability = getattr(provider, "capability", name)
        worker = JsonlProcessProvider(provider.name, worker_capability, provider.model, [str(python), "-m", "specialist", "_worker", "--capability", worker_capability, "--backend", worker_backend], timeout_seconds=timeout if worker_capability == name else self.TIMEOUTS.get(worker_capability, timeout), cpu_limit_seconds=timeout + 10, memory_limit_bytes=memory_limit_bytes, env=worker_env, log_path=self.cache.logs / f"{name.replace('.', '__').replace('@', '__')}.worker.log")
        # Preserve provider metadata across the process boundary. Routing and
        # policy run in Core, so a worker must retain the same model identity,
        # resource profile and locality facts as its in-process counterpart.
        for attribute in (
            "preferred_model",
            "quality",
            "latency_ms",
            "memory_requirement_mb",
            "disk_requirement_mb",
            "license",
            "commercial",
            "requires_local_model_directory",
            "remote",
            "node_id",
        ):
            try:
                if hasattr(provider, attribute):
                    setattr(worker, attribute, getattr(provider, attribute))
            except Exception:
                # Metadata is advisory; provider startup remains responsible
                # for reporting the actionable configuration error.
                continue
        if hasattr(provider, "supported_devices"):
            worker.supported_devices = tuple(provider.supported_devices)
        if hasattr(provider, "supported_platforms"):
            worker.supported_platforms = tuple(provider.supported_platforms)
        worker.requires_verified_artifact = artifact_required
        worker.requires_local_model_directory = bool(getattr(provider, "requires_local_model_directory", False))
        return worker

    def _verify_installation(self, installation):
        if not installation:
            raise ValueError("model installation is missing")
        artifact = installation.get("artifact_path")
        if not artifact:
            raise ValueError("model artifact path is missing")
        if installation.get("artifact_kind") == "bundle":
            verified = self.models_manager.verify_bundle(Path(artifact), Path(installation.get("artifact_manifest") or Path(artifact) / "artifact-manifest.json"))
            expected = installation.get("sha256")
            if expected and verified.get("manifest_sha256") != expected:
                raise ValueError(f"bundle manifest checksum mismatch: expected {expected}, got {verified.get('manifest_sha256')}")
            return verified
        return {"sha256": self.models_manager.verify(Path(artifact), installation.get("sha256"))}

    def metrics(self):
        with self._metrics_lock:
            return dict(self._metrics)

    def _router(self) -> DeterministicRouter:
        installations = {name: self.cache.installation(name) for name in CAPABILITIES}
        return DeterministicRouter(policy=self.policy, specs=CAPABILITIES, providers=self.providers, installations=installations, benchmarks=self.benchmarks, hardware=detect_hardware())

    def _route_provider(self, capability: str, provider_name: str):
        for key, provider in self.providers.items():
            if getattr(provider, "name", None) == provider_name and getattr(provider, "capability", capability) == capability:
                return provider
            if key == capability and getattr(provider, "name", None) == provider_name:
                return provider
            if key == f"{capability}@{provider_name}" or (key == provider_name and getattr(provider, "capability", capability) == capability):
                return provider
        return self.providers[capability]

    def _provider_for_installation(self, capability: str, installation=None):
        provider_name = installation.get("provider") if isinstance(installation, dict) else None
        if isinstance(provider_name, str) and provider_name:
            return self._route_provider(capability, provider_name)
        return self.providers[capability]

    def explain(self, capability: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return the deterministic routing decision without executing input."""
        canonical = resolve_capability(capability)
        try:
            return self._router().route(canonical, options or {})
        except RoutingError as exc:
            if exc.explanation:
                return exc.explanation
            raise

    def readiness(self):
        hardware = detect_hardware()
        capability_states = []
        for spec in CAPABILITIES.values():
            installation = self.cache.installation(spec.name)
            provider = self._provider_for_installation(spec.name, installation)
            error = self.cache.error_state(spec.name)
            check = {}
            state = "ready"
            reason = None
            if error:
                state = "error"
                reason = error.get("message", "capability has a persisted error state")
            else:
                try:
                    check = provider.doctor(hardware) or {}
                except Exception as exc:
                    check = {"status": "not ready", "error": {"code": "provider_doctor_failed", "message": str(exc)}}
                model_spec = spec.model_spec(self._model_for(spec, installation, hardware))
                platform = target_id(hardware)
                if platform not in model_spec.platforms:
                    check = {**check, "status": "not ready", "error": {"code": "unsupported_platform", "message": f"model is not published for {platform}"}}
                effective_memory_mb = min((hardware.get("memory_gb") or 0) * 1024, (hardware.get("memory_limit_gb") or hardware.get("memory_gb") or 0) * 1024)
                if effective_memory_mb and effective_memory_mb < model_spec.memory_mb:
                    check = {**check, "status": "not ready", "error": {"code": "insufficient_memory", "message": f"model requires {model_spec.memory_mb} MiB but host budget is {round(effective_memory_mb)} MiB"}}
                if check.get("status") != "ready":
                    state = "unavailable"
                    reason = (check.get("error") or {}).get("message") or check.get("message") or "provider is not ready"
                elif installation and installation.get("status") in {"corrupt", "error"}:
                    state = installation["status"]
                    reason = installation.get("message") or f"model state is {installation['status']}"
                elif self.backend == "real" or getattr(provider, "requires_verified_artifact", False):
                    artifact = installation.get("artifact_path") if installation else None
                    digest = installation.get("sha256") if installation else None
                    if not artifact or not digest:
                        state = "unconfigured"
                        reason = "a verified model artifact is required"
                    else:
                        try:
                            self._verify_installation(installation)
                        except Exception as exc:
                            state = "corrupt"
                            reason = str(exc)
            capability_states.append({
                "capability": spec.name,
                "provider": getattr(provider, "name", spec.provider),
                "model": self._model_for(spec, installation, hardware),
                "status": state,
                "reason": reason,
                "installation": installation,
                "check": check,
            })
        ready_count = sum(item["status"] == "ready" for item in capability_states)
        unready = len(capability_states) - ready_count
        if unready == 0:
            status = "ready"
        elif ready_count == 0 or self.backend == "real":
            status = "not_ready"
        else:
            status = "degraded"
        return {
            "status": status,
            "installed_capabilities": sum(item["installation"] is not None for item in capability_states),
            "ready_capabilities": ready_count,
            "capabilities": len(capability_states),
            "error_capabilities": sum(item["status"] in {"error", "corrupt"} for item in capability_states),
            "unready_capabilities": unready,
            "backend": self.backend,
            "isolate": self.isolate,
            "details": capability_states,
        }

    def install(self, target: str, source: str | None = None, sha256: str | None = None, with_dependencies=None, model: str | None = None, provider_override=None) -> list[dict[str, Any]]:
        names = BUNDLES.get(target.lower())
        if names is None:
            names = [resolve_capability(target)]
        if source and len(names) != 1:
            raise ValueError("--source can only be used with one capability")
        if source and source.lower().startswith(("http://", "https://")) and not sha256:
            raise ValueError("remote model sources require --sha256")
        install_dependencies = self.with_dependencies if with_dependencies is None else with_dependencies
        installed = []
        for name in names:
            spec = CAPABILITIES[name]
            with self.cache.capability_lock(name):
                existing = self.cache.installation(name)
                if existing and not source and not install_dependencies and (provider_override is None or existing.get("provider") == getattr(provider_override, "name", spec.provider)):
                    installed.append({"capability": name, "provider": existing.get("provider", spec.provider), "model": existing.get("model", spec.model), "status": existing.get("status", "ready"), "already_installed": True})
                    continue
                provider = provider_override if provider_override is not None and len(names) == 1 else self.providers[name]
                registered_models = {item.id for item in spec.models}
                if model is not None and model not in registered_models:
                    raise ValueError(f"model '{model}' is not registered for {name}")
                preferred_model = getattr(provider, "preferred_model", None)
                selected_model = (
                    model
                    if model is not None
                    else preferred_model
                    if preferred_model in registered_models
                    else self._model_for(spec, existing)
                )
                model_spec = spec.model_spec(selected_model)
                if provider_override is not None and len(names) == 1:
                    # Alternate providers (for example system_tts) live under
                    # a qualified key so installing one route never replaces
                    # the Fish primary adapter for later quality requests.
                    target_key = name if getattr(provider, "name", spec.provider) == spec.provider else f"{name}@{getattr(provider, 'name', 'override')}"
                    self.providers[target_key] = provider
                if hasattr(provider, "model"):
                    provider.model = selected_model
                dependency_env = None
                try:
                    if install_dependencies and self.backend != "fallback" and spec.optional_dependency in PROVIDER_REQUIREMENTS and PROVIDER_REQUIREMENTS[spec.optional_dependency]:
                        # ``auto`` initially selects fallbacks when the host
                        # interpreter lacks the optional package. Once the
                        # isolated environment is requested, switch to the
                        # real provider before installing its artifact.
                        if not getattr(provider, "requires_verified_artifact", False):
                            provider = provider_map("real")[name]
                            provider._allow_unverified_models = self.allow_unverified_models
                        dependency_env = self.environments.ensure(spec.provider, PROVIDER_REQUIREMENTS[spec.optional_dependency])
                        provider = self._worker_provider(name, provider, dependency_env["python"], requires_verified_artifact=True)
                        self.providers[name] = provider
                    details = provider.install(self.cache, spec)
                    if details is None:
                        details = {}
                    if not isinstance(details, dict):
                        raise WorkerError("provider install returned a non-object", code="provider_install_invalid", retryable=False)
                    auto_source = source
                    auto_sha256 = sha256
                    # Registry artifacts are fetched automatically only for a
                    # real/optional provider. The dependency-free fallback is
                    # intentionally offline and must never pull model weights.
                    if auto_source is None and self.backend != "fallback" and getattr(provider, "requires_verified_artifact", False):
                        if model_spec.artifact_kind == "bundle" and model_spec.artifact_files:
                            auto_source = "bundle://registry"
                        elif model_spec.artifact_url and model_spec.artifact_sha256:
                            auto_source = model_spec.artifact_url
                            auto_sha256 = model_spec.artifact_sha256
                    if auto_source:
                        if getattr(provider, "requires_provider_environment", False) and dependency_env is None:
                            raise WorkerError("this provider artifact must be installed into an isolated environment; rerun with --with-dependencies", code="provider_environment_required", retryable=False)
                        is_bundle = model_spec.artifact_kind == "bundle" and not source
                        artifact_root = self.cache.models / name.replace(".", "__") / selected_model
                        if is_bundle:
                            artifact_path = artifact_root
                        else:
                            filename = model_spec.artifact_filename
                            if not filename:
                                filename = Path(auto_source.split("?", 1)[0]).name or selected_model
                            artifact_path = artifact_root / filename
                        self.models_manager.ensure_capacity(artifact_path, model_spec.disk_mb * 1024 * 1024)
                        marker_fields = {"artifact_kind": "bundle" if is_bundle else "file", "artifact_entrypoint": model_spec.artifact_entrypoint, "artifact_manifest": str(artifact_path / "artifact-manifest.json") if is_bundle else None}
                        self.cache.mark_installed(name, provider.name, selected_model, status="downloading", license_name=spec.license, source=auto_source, sha256=auto_sha256, artifact_path=artifact_path, commercial=spec.commercial, source_url=spec.source_url, **marker_fields)
                        if is_bundle:
                            artifact = self.models_manager.download_bundle(model_spec.artifact_files, artifact_path, entrypoint=model_spec.artifact_entrypoint)
                        else:
                            artifact = self.models_manager.download(auto_source, artifact_path, expected_sha256=auto_sha256)
                        if dependency_env and artifact_path.suffix == ".whl":
                            details["provider_artifact"] = self.environments.install_artifact(spec.provider, artifact_path)
                        self.cache.mark_installed(name, provider.name, selected_model, status="ready", license_name=spec.license, source=auto_source, sha256=artifact["sha256"], artifact_path=artifact_path, commercial=spec.commercial, source_url=spec.source_url, **marker_fields)
                        details.update({"artifact": artifact, "verification": "sha256"})
                    installed.append({"capability": name, "provider": getattr(provider, "name", spec.provider), "model": selected_model, "environment": dependency_env, "registry_model": {"source_url": spec.source_url, "memory_mb": model_spec.memory_mb, "disk_mb": model_spec.disk_mb, "platforms": list(model_spec.platforms), "devices": list(model_spec.devices), "artifact_url": model_spec.artifact_url, "artifact_sha256": model_spec.artifact_sha256, "artifact_kind": model_spec.artifact_kind, "artifact_entrypoint": model_spec.artifact_entrypoint, "artifact_files": [{"path": item.path, "url": item.url, "sha256": item.sha256} for item in model_spec.artifact_files]}, **details})
                except Exception as exc:
                    self.cache.mark_error(name, provider.name, selected_model, str(exc), source=source)
                    artifact_path = self.cache.models / name.replace(".", "__") / selected_model
                    if artifact_path.is_dir():
                        import shutil

                        shutil.rmtree(artifact_path, ignore_errors=True)
                    else:
                        artifact_path.unlink(missing_ok=True)
                    raise
        return installed

    def doctor(self, fix=False) -> dict[str, Any]:
        hardware = detect_hardware()
        capabilities = []
        fixes = []
        warnings = ["Built-in providers are dependency-free fallbacks. Install the optional backend and a verified model artifact for production inference."]
        if not hardware.get("ffmpeg"):
            warnings.append("FFmpeg is not available; audio and document providers may not work. Install it with the system package manager.")
        if not hardware.get("supported_target"):
            warnings.append("This platform is outside the primary macOS Apple Silicon support target; validate providers before production use.")
        for spec in CAPABILITIES.values():
            installation = self.cache.installation(spec.name)
            provider = self._provider_for_installation(spec.name, installation)
            details = provider.doctor(hardware)
            model_spec = spec.model_spec(self._model_for(spec, installation, hardware))
            platform = target_id(hardware)
            if platform not in model_spec.platforms:
                details = {**details, "status": "not ready", "error": {"code": "unsupported_platform", "message": f"model is not published for {platform}"}}
            effective_memory_mb = min((hardware.get("memory_gb") or 0) * 1024, (hardware.get("memory_limit_gb") or hardware.get("memory_gb") or 0) * 1024)
            if effective_memory_mb and effective_memory_mb < model_spec.memory_mb:
                details = {**details, "status": "not ready", "error": {"code": "insufficient_memory", "message": f"model requires {model_spec.memory_mb} MiB but host budget is {round(effective_memory_mb)} MiB"}}
            environment = self.environments.status(spec.provider) if spec.optional_dependency in PROVIDER_REQUIREMENTS and PROVIDER_REQUIREMENTS[spec.optional_dependency] else None
            if environment and environment.get("status") == "ready" and not self.environments.verify(spec.provider, PROVIDER_REQUIREMENTS[spec.optional_dependency]):
                environment = {**environment, "status": "corrupt", "message": "provider environment imports are not usable"}
            if fix and self.with_dependencies and self.backend != "fallback" and spec.optional_dependency in PROVIDER_REQUIREMENTS and PROVIDER_REQUIREMENTS[spec.optional_dependency] and environment and environment.get("status") != "ready":
                try:
                    if not getattr(provider, "requires_verified_artifact", False):
                        provider = provider_map("real")[spec.name]
                        provider._allow_unverified_models = self.allow_unverified_models
                    environment = self.environments.ensure(spec.provider, PROVIDER_REQUIREMENTS[spec.optional_dependency])
                    provider = self._worker_provider(spec.name, provider, environment["python"], requires_verified_artifact=True)
                    self.providers[spec.name] = provider
                    details = provider.doctor(hardware)
                except EnvironmentError as exc:
                    fixes.append({"capability": spec.name, "status": "failed", "message": str(exc)})
            if fix and details.get("status") != "ready":
                fixes.append({"capability": spec.name, "status": "manual", "message": "Provider reported an issue; install its optional backend and rerun doctor."})
            verification = None
            if installation and installation.get("artifact_path"):
                try:
                    verified = self._verify_installation(installation)
                    verification = {"status": "verified", **verified}
                except Exception as exc:
                    verification = {"status": "corrupt", "error": str(exc)}
                    self.cache.update_state(spec.name, "corrupt")
                    if fix:
                        model_spec = spec.model_spec(self._model_for(spec, installation, hardware))
                        if (model_spec.artifact_kind == "bundle" and model_spec.artifact_files) or (model_spec.artifact_url and model_spec.artifact_sha256):
                            try:
                                self.cache.remove_model(spec.name)
                                self.install(spec.name, source=model_spec.artifact_url, sha256=model_spec.artifact_sha256, with_dependencies=self.with_dependencies)
                                installation = self.cache.installation(spec.name)
                                verification = {"status": "verified", "sha256": model_spec.artifact_sha256}
                                fixes.append({"capability": spec.name, "status": "repaired", "message": "redownloaded and verified the registered artifact"})
                            except Exception as repair_exc:
                                fixes.append({"capability": spec.name, "status": "failed", "message": str(repair_exc)})
                        else:
                            fixes.append({"capability": spec.name, "status": "manual", "message": "No verified artifact is registered; reinstall with --source and --sha256."})
            error_state = self.cache.error_state(spec.name)
            state = "ready" if installation else ("error" if error_state else "not installed")
            if verification and verification.get("status") == "corrupt":
                state = "corrupt"
            if details.get("status") != "ready":
                state = "unavailable"
            capabilities.append({"capability": spec.name, "provider": getattr(provider, "name", spec.provider), "model": self._model_for(spec, installation, hardware), "installation": installation, "error": error_state, "environment": environment, "verification": verification, "registry": {"source_url": spec.source_url, "models": [model.id for model in spec.models]}, **details, "status": state})
        from . import __version__

        return {"version": __version__, "home": str(self.cache.home), "system": hardware, "capabilities": capabilities, "fixes": fixes, "warnings": warnings}

    def models(self):
        output = []
        for spec in CAPABILITIES.values():
            installation = self.cache.installation(spec.name)
            provider = self._provider_for_installation(spec.name, installation)
            state = "not installed"
            verification = None
            if installation:
                state = installation.get("status", "ready")
                artifact = installation.get("artifact_path")
                if artifact:
                    try:
                        verification = {"status": "verified", **self._verify_installation(installation)}
                    except Exception as exc:
                        state = "corrupt"
                        verification = {"status": "corrupt", "error": str(exc)}
            error_state = self.cache.error_state(spec.name)
            if not installation and error_state:
                state = "error"
            registry_model = spec.model_spec(self._model_for(spec, installation))
            output.append({"capability": spec.name, "provider": getattr(provider, "name", spec.provider), "model": self._model_for(spec, installation), "status": state, "installation": installation, "error": error_state, "registry": {"source_url": spec.source_url, "recommended": registry_model.recommended, "memory_mb": registry_model.memory_mb, "disk_mb": registry_model.disk_mb, "platforms": list(registry_model.platforms), "devices": list(registry_model.devices), "artifact_url": registry_model.artifact_url, "artifact_sha256": registry_model.artifact_sha256, "artifact_kind": registry_model.artifact_kind, "artifact_entrypoint": registry_model.artifact_entrypoint, "artifact_files": [{"path": item.path, "url": item.url, "sha256": item.sha256} for item in registry_model.artifact_files]}, "verification": verification})
        return output

    def remove_model(self, target):
        names = BUNDLES.get(target.lower(), [resolve_capability(target)])
        output = []
        for name in names:
            with self._locks[name]:
                if name in self._loaded:
                    active_provider = self._active_providers.get(name, self.providers[name])
                    active_provider.unload()
                    close_provider = getattr(active_provider, "close", None)
                    if callable(close_provider):
                        close_provider()
                    self._loaded.discard(name)
                    self._active_providers.pop(name, None)
                    self._last_used.pop(name, None)
                output.append({"capability": name, "removed": self.cache.remove_model(name)})
        return output

    def pin_model(self, target, pinned=True):
        names = BUNDLES.get(target.lower(), [resolve_capability(target)])
        output = []
        for name in names:
            with self._locks[name]:
                if self.cache.installation(name) is None:
                    if self.with_dependencies:
                        self.install(name, with_dependencies=True)
                    else:
                        self.install(name, with_dependencies=False)
                output.append({"capability": name, "pinned": self.cache.set_pinned(name, pinned)["pinned"]})
        return output

    def clean_cache(self, max_age_seconds=None, max_entries=None):
        return {"removed_results": self.cache.clean_results(max_age_seconds=max_age_seconds, max_entries=max_entries)}

    def replay(self, run_id: str) -> dict[str, Any]:
        """Replay a cached deterministic result by its cache/run identifier."""
        if not isinstance(run_id, str) or not run_id or any(char not in "0123456789abcdef" for char in run_id.lower()):
            raise ValueError("run_id must be a hexadecimal cache identifier")
        value = self.cache.read_result(run_id)
        if value is None:
            raise KeyError(f"run '{run_id}' was not found")
        validate_envelope(value)
        value.setdefault("trace", []).append({"stage": "replay", "run_id": run_id})
        value.setdefault("performance", {})["replayed"] = True
        return value

    def run_graph(self, graph, input_path, options: dict[str, Any] | None = None) -> dict[str, Any]:
        return graph.execute(self, input_path, options or {})

    def run_cascade(self, cascade, input_path, options: dict[str, Any] | None = None) -> dict[str, Any]:
        return cascade.execute(self, input_path, options or {})

    def open_session(self, capability: str, options: dict[str, Any] | None = None):
        canonical = resolve_capability(capability)
        return self.sessions.open(canonical, options or {})

    def benchmark(self, capability: str, input_path: str | Path, *, runs: int = 3, options: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if isinstance(runs, bool) or int(runs) <= 0 or int(runs) > 100:
            raise ValueError("runs must be between 1 and 100")
        canonical = resolve_capability(capability)
        values = []
        for index in range(int(runs)):
            started = time.perf_counter()
            result = self.run(canonical, input_path, {**(options or {}), "_benchmark_run": index})
            if result.get("error"):
                raise ValueError(f"benchmark input failed: {result['error'].get('code')}: {result['error'].get('message')}")
            measured = (time.perf_counter() - started) * 1000
            performance = result.get("performance") or {}
            record = BenchmarkRecord(canonical, result.get("provider", "unknown"), result.get("model", "unknown"), detect_hardware(), measured, float(performance.get("latency_ms") or measured), performance.get("memory_mb"), result.get("confidence"), 1)
            values.append(self.benchmarks.record(record))
        return values

    def provider_manifests(self) -> list[dict[str, Any]]:
        values = [item.to_dict() for item in builtin_manifests()]
        known = {item["provider"] for item in values}
        values.extend(item.to_dict() for item in self.provider_catalog.list() if item.provider not in known)
        return values

    def import_voice(self, source: str | Path, name: str, *, provider_assets: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.voices.import_voice(source, name, provider_assets=provider_assets)

    def list_voices(self) -> list[dict[str, Any]]:
        return self.voices.list()

    def remove_voice(self, value: str) -> bool:
        return self.voices.remove(value)

    def provider_lifecycle(self, provider: str, action: str) -> dict[str, Any]:
        if provider != "fish_audio":
            raise ValueError(f"provider lifecycle is not implemented for '{provider}'")
        adapter = self.providers.get("speech.synthesize")
        if hasattr(adapter, "_cache"):
            adapter._cache = self.cache
        lifecycle = getattr(adapter, "lifecycle", None)
        if lifecycle is None:
            # Isolated runtimes intentionally do not expose a child process'
            # server object. Lifecycle commands are operator operations and
            # use a direct adapter instance in normal CLI mode.
            from .providers.fish_audio import FishAudioProvider

            adapter = FishAudioProvider("speech.synthesize")
            adapter._cache = self.cache
            lifecycle = adapter.lifecycle
        if action == "start":
            return lifecycle.start(persist=True)
        if action == "stop":
            return lifecycle.stop()
        if action == "restart":
            return lifecycle.restart(persist=True)
        if action in {"status", "health"}:
            return lifecycle.health()
        raise ValueError("provider action must be start, stop, restart or status")

    def packs(self):
        from .packs import PACKS

        return [pack.to_dict() for pack in PACKS]

    def install_pack(self, name: str, *, with_dependencies: bool | None = None) -> list[dict[str, Any]]:
        pack = get_pack(name)
        values = []
        for capability in pack.capabilities:
            values.extend(self.install(capability, with_dependencies=with_dependencies))
        return values

    def close(self):
        self.sessions.close_all()
        for name in list(self._loaded):
            active_provider = self._active_providers.get(name, self.providers[name])
            try:
                active_provider.unload()
                close_provider = getattr(active_provider, "close", None)
                if callable(close_provider):
                    close_provider()
                self.cache.update_state(name, "unloaded")
            finally:
                self._loaded.discard(name)
                self._active_providers.pop(name, None)
                self._last_used.pop(name, None)
        # A provider can fail while starting before it is marked loaded. Give
        # lifecycle-aware adapters a final chance to reap owned child servers.
        seen = set()
        for provider in self.providers.values():
            identity = id(provider)
            if identity in seen:
                continue
            seen.add(identity)
            close_provider = getattr(provider, "close", None)
            if callable(close_provider):
                try:
                    close_provider()
                except Exception:
                    pass

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        self.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def _evict_if_needed(self, exclude):
        if exclude in self._loaded or len(self._loaded) < self.max_loaded:
            return
        candidates = [name for name in self._loaded if name != exclude and not (self.cache.installation(name) or {}).get("pinned")]
        if not candidates:
            return
        victim = min(candidates, key=lambda name: self._last_used.get(name, 0))
        active_provider = self._active_providers.get(victim, self.providers[victim])
        try:
            active_provider.unload()
            self.cache.update_state(victim, "unloaded")
        finally:
            self._loaded.discard(victim)
            self._active_providers.pop(victim, None)
            self._last_used.pop(victim, None)

    def run(self, capability: str, input_path: str | Path, options: dict[str, Any] | None = None) -> dict[str, Any]:
        canonical = resolve_capability(capability)
        with self._locks[canonical]:
            return self._run(capability, input_path, options)

    def _finish(self, envelope: dict[str, Any]) -> dict[str, Any]:
        # Older cache entries remain readable while new calls always expose the
        # complete Observation Protocol shape.
        envelope.setdefault("observations", [])
        envelope.setdefault("evidence", [])
        envelope.setdefault("artifacts", [])
        envelope.setdefault("metrics", envelope.get("performance") or {})
        envelope.setdefault("provenance", {})
        envelope.setdefault("confidence", None)
        envelope.setdefault("trace", [])
        try:
            validate_envelope(envelope)
        except (TypeError, ValueError, KeyError) as exc:
            envelope = ResultEnvelope.failure(envelope.get("capability", "unknown"), envelope.get("provider", "unknown"), envelope.get("model", "unknown"), envelope.get("input", {}), "invalid_provider_result", str(exc)).to_dict()
        performance = envelope.get("performance") or {}
        with self._metrics_lock:
            self._metrics["requests_total"] += 1
            self._metrics["latency_ms_total"] += int(performance.get("latency_ms") or 0)
            if performance.get("cached"):
                self._metrics["cache_hits_total"] += 1
            if envelope.get("error") is not None:
                self._metrics["errors_total"] += 1
        self.logger.emit("capability.run", capability=envelope.get("capability"), provider=envelope.get("provider"), model=envelope.get("model"), input_sha256=(envelope.get("input") or {}).get("sha256"), input_size_bytes=(envelope.get("input") or {}).get("size_bytes"), latency_ms=performance.get("latency_ms"), cached=performance.get("cached", False), success=envelope.get("error") is None, error_code=(envelope.get("error") or {}).get("code"))
        return envelope

    def _collect_artifacts(self, capability: str, result: dict[str, Any]) -> list[dict[str, Any]]:
        """Promote provider-created files to the content-addressed artifact store."""
        references: list[dict[str, Any]] = []
        existing = result.get("artifacts")
        if isinstance(existing, list):
            references.extend(item for item in existing if isinstance(item, dict) and item.get("id"))
        for key in ("preview", "artifact_path"):
            value = result.get(key)
            if not isinstance(value, str) or value.startswith("artifact://"):
                continue
            path = Path(value).expanduser()
            try:
                if path.is_file():
                    reference = self.artifacts.put_file(path, metadata={"capability": capability, "result_key": key})
                    if reference.to_dict() not in references:
                        references.append(reference.to_dict())
            except (ArtifactError, OSError):
                # A provider result remains useful when an optional preview
                # cannot be copied; the original result path is preserved.
                continue
        audio = result.get("audio")
        if isinstance(audio, dict):
            path_value = audio.get("path")
            if isinstance(path_value, str) and not path_value.startswith("artifact://"):
                path = Path(path_value).expanduser()
                temporary_output = bool(audio.get("temporary"))
                try:
                    if path.is_file():
                        reference = self.artifacts.put_file(path, mime=audio.get("mime"), metadata={"capability": capability, "result_key": "audio"})
                        audio["artifact"] = reference.uri
                        audio["mime"] = reference.mime
                        audio.pop("path", None)
                        audio.pop("temporary", None)
                        if reference.to_dict() not in references:
                            references.append(reference.to_dict())
                        if temporary_output:
                            path.unlink(missing_ok=True)
                except (ArtifactError, OSError):
                    # Do not leave generated audio in the temporary area when
                    # artifact persistence fails; non-temporary provider
                    # previews remain available for diagnostics.
                    if temporary_output:
                        try:
                            path.unlink(missing_ok=True)
                        except OSError:
                            pass
                    pass
        return references

    def _speech_fallback(self, canonical: str, input_path: str | Path, options: dict[str, Any], error: WorkerError | Exception):
        if canonical != "speech.synthesize" or options.get("provider") or options.get("_fallback_attempted"):
            return None
        error_code = getattr(error, "code", None)
        if not getattr(error, "retryable", False) and error_code not in {"fish_audio_start_not_configured", "fish_audio_not_ready"}:
            # Protocol, privacy, validation and malformed-output failures are
            # actionable provider drift, not availability conditions.
            return None
        rule = self.policy.resolve(canonical, options)
        if not bool(rule.get("fallback", True)):
            return None
        fallback = self.providers.get("speech.synthesize@system_tts")
        if fallback is None:
            return None
        fallback_options = {**options, "provider": "system_tts", "_fallback_attempted": True}
        value = self._run(canonical, input_path, fallback_options)
        if value.get("error") is None:
            value.setdefault("warnings", []).append("QUALITY_PROFILE_DEGRADED: fish_audio unavailable; used system_tts fallback")
            value.setdefault("trace", []).append({"stage": "fallback", "from": "fish_audio", "to": "system_tts", "reason": str(error)})
            value.setdefault("metrics", {})["fallback"] = True
        return value

    @staticmethod
    def _memory_mb():
        try:
            import resource

            value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            if sys.platform == "darwin":
                return round(value / 1024 / 1024, 1)
            return round(value / 1024, 1)
        except (ImportError, OSError):
            return None

    def _run(self, capability: str, input_path: str | Path, options: dict[str, Any] | None = None) -> dict[str, Any]:
        raw_options = {} if options is None else options
        canonical = resolve_capability(capability)
        spec = CAPABILITIES[canonical]
        provider = self.providers[canonical]
        try:
            path = Path(input_path).expanduser()
        except TypeError as exc:
            return self._finish(ResultEnvelope.failure(canonical, spec.provider, spec.model, {"type": spec.modality, "path": str(input_path)}, "invalid_input", str(exc)).to_dict())
        input_info = {"type": spec.modality, "path": str(path)}
        if not isinstance(raw_options, dict):
            return self._finish(ResultEnvelope.failure(canonical, spec.provider, spec.model, {"type": CAPABILITIES[canonical].modality, "path": str(input_path)}, "invalid_options", "options must be an object").to_dict())
        options = dict(raw_options)
        try:
            policy_rule = self.policy.resolve(canonical, options)
        except PolicyError as exc:
            return self._finish(ResultEnvelope.failure(canonical, spec.provider, spec.model, input_info, "invalid_policy", str(exc)).to_dict())
        # Carry the resolved privacy decision across the provider boundary so
        # remote reference-audio checks cannot diverge from Runtime policy.
        options.setdefault("allow_remote", bool(policy_rule.get("allow_remote", False)))
        try:
            json.dumps(options, sort_keys=True, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError) as exc:
            return self._finish(ResultEnvelope.failure(canonical, spec.provider, spec.model, input_info, "invalid_options", str(exc)).to_dict())
        if "timeout_seconds" in options:
            try:
                timeout = float(options["timeout_seconds"])
            except (TypeError, ValueError):
                return self._finish(ResultEnvelope.failure(canonical, spec.provider, spec.model, input_info, "invalid_options", "timeout_seconds must be numeric").to_dict())
            if timeout <= 0 or timeout > self.TIMEOUTS[canonical]:
                return self._finish(ResultEnvelope.failure(canonical, spec.provider, spec.model, input_info, "invalid_options", f"timeout_seconds must be between 0 and {self.TIMEOUTS[canonical]}").to_dict())
            options["timeout_seconds"] = timeout
        try:
            route = self._router().route(canonical, options)
        except RoutingError as exc:
            return self._finish(ResultEnvelope.failure(canonical, spec.provider, spec.model, input_info, "routing_unavailable", str(exc), retryable=False, routing=exc.explanation).to_dict())
        selected = route["selected"] or {}
        selected_model = str(selected.get("model") or spec.model)
        route_latency = selected.get("estimated_latency_ms")
        provider = self._route_provider(canonical, str(selected.get("provider") or spec.provider))
        requested_device = options.get("device", "cpu")
        if requested_device not in getattr(provider, "supported_devices", ("cpu",)):
            return self._finish(ResultEnvelope.failure(canonical, spec.provider, spec.model, input_info, "invalid_options", f"device must be one of {list(getattr(provider, 'supported_devices', ('cpu',)))}").to_dict())
        installation = self.cache.installation(canonical)
        if installation and installation.get("model") and installation.get("provider") == getattr(provider, "name", spec.provider):
            selected_model = self._model_for(spec, installation)
        requested_model_spec = spec.model_spec(selected_model)
        policy_decision = self.policy.evaluate(capability=canonical, provider=provider, model=requested_model_spec, options=options, estimated_latency_ms=route_latency)
        if not policy_decision.allowed:
            return self._finish(ResultEnvelope.failure(canonical, provider.name, selected_model, input_info, "policy_rejected", "; ".join(policy_decision.reasons), retryable=False).to_dict())
        if requested_device not in requested_model_spec.devices:
            return self._finish(ResultEnvelope.failure(canonical, spec.provider, spec.model, input_info, "unsupported_device", f"model {requested_model_spec.id} does not support device {requested_device}").to_dict())
        hardware = detect_hardware()
        effective_memory_mb = min((hardware.get("memory_gb") or 0) * 1024, (hardware.get("memory_limit_gb") or hardware.get("memory_gb") or 0) * 1024)
        if (self.backend == "real" or getattr(provider, "requires_verified_artifact", False)) and effective_memory_mb and effective_memory_mb < requested_model_spec.memory_mb:
            return self._finish(ResultEnvelope.failure(canonical, spec.provider, requested_model_spec.id, input_info, "insufficient_memory", f"model requires {requested_model_spec.memory_mb} MiB but host budget is {round(effective_memory_mb)} MiB").to_dict())
        if not path.exists():
            return self._finish(ResultEnvelope.failure(canonical, spec.provider, spec.model, input_info, "input_not_found", f"Input file does not exist: {path}").to_dict())
        if not path.is_file():
            return self._finish(ResultEnvelope.failure(canonical, spec.provider, spec.model, input_info, "input_not_file", f"Input path is not a file: {path}").to_dict())
        if path.stat().st_size > 512 * 1024 * 1024:
            return self._finish(ResultEnvelope.failure(canonical, spec.provider, spec.model, input_info, "input_too_large", "Input exceeds the 512 MiB safety limit.").to_dict())
        if rust_validate_input:
            try:
                rust_validate_input(path.stat().st_size, 512 * 1024 * 1024, path.is_file())
            except ValueError as exc:
                return self._finish(ResultEnvelope.failure(canonical, spec.provider, spec.model, input_info, "unsafe_input", str(exc)).to_dict())
        input_info.update({"size_bytes": path.stat().st_size, "sha256": self.cache.input_hash(path)})
        if hasattr(provider, "model"):
            provider.model = selected_model
        key = self.cache.result_key(path, canonical, provider.name, selected_model, options)
        cached = self.cache.read_result(key)
        if cached:
            try:
                validate_envelope(cached)
                if cached.get("capability") != canonical or cached.get("provider") != provider.name or cached.get("model") != selected_model:
                    raise ValueError("cached result identity does not match request")
            except (TypeError, ValueError, KeyError):
                self.cache.remove_result(key)
            else:
                cached.setdefault("performance", {})["cached"] = True
                cached["performance"]["latency_ms"] = 0
                return self._finish(cached)
        if self.cache.installation(canonical) is None:
            try:
                if self.with_dependencies:
                    self.install(canonical, with_dependencies=True, model=selected_model, provider_override=provider)
                    if getattr(provider, "name", spec.provider) == spec.provider:
                        provider = self.providers.get(canonical, provider)
                    installation = self.cache.installation(canonical)
                    selected_model = self._model_for(spec, installation)
                else:
                    self.install(canonical, with_dependencies=False, model=selected_model, provider_override=provider)
                    if getattr(provider, "name", spec.provider) == spec.provider:
                        provider = self.providers.get(canonical, provider)
                    installation = self.cache.installation(canonical)
                    selected_model = self._model_for(spec, installation)
                if hasattr(provider, "model"):
                    provider.model = selected_model
                # Installation can promote a fallback to a real provider and
                # can persist a hardware-aware model choice. Recompute the
                # cache identity before reading or writing the result.
                key = self.cache.result_key(path, canonical, provider.name, selected_model, options)
            except WorkerError as exc:
                return self._finish(ResultEnvelope.failure(canonical, spec.provider, spec.model, input_info, exc.code, str(exc), retryable=exc.retryable).to_dict())
            except Exception as exc:
                return self._finish(ResultEnvelope.failure(canonical, spec.provider, spec.model, input_info, "provider_install_failed", str(exc), retryable=False).to_dict())
        self._active_providers[canonical] = provider
        cold_start = canonical not in self._loaded
        started = time.perf_counter()
        try:
            self._evict_if_needed(canonical)
            self.cache.update_state(canonical, "loading")
            provider.load()
            self._loaded.add(canonical)
            self._last_used[canonical] = time.monotonic()
            self.cache.update_state(canonical, "running")
            result, warnings = provider.infer(path, options, self.cache)
            performance = {"latency_ms": round((time.perf_counter() - started) * 1000), "device": requested_device, "memory_mb": self._memory_mb(), "cached": False, "cold_start": cold_start}
            from . import __version__

            artifacts = self._collect_artifacts(canonical, result)
            observations = build_observations(canonical, result, provider=provider.name, model=selected_model, source=input_info, runtime_version=__version__)
            envelope = ResultEnvelope(
                canonical,
                provider.name,
                selected_model,
                input_info,
                result=result,
                performance=performance,
                warnings=warnings,
                observations=observations,
                evidence=evidence_from_observations(observations),
                artifacts=artifacts,
                metrics={**performance, "observation_count": len(observations), "artifact_count": len(artifacts)},
                provenance={"source": input_info, "provider": provider.name, "model_version": selected_model, "runtime_version": __version__, "transformations": []},
                confidence=aggregate_confidence(observations),
                trace=[{"stage": "routing", **route}, {"stage": "policy", "profile": policy_rule.get("profile"), "constraints": policy_rule, "decision": policy_decision.to_dict()}],
            ).to_dict()
            minimum_confidence = policy_rule.get("min_confidence")
            if minimum_confidence is not None and envelope.get("confidence") is not None and float(envelope["confidence"]) < float(minimum_confidence):
                envelope["error"] = {"code": "low_confidence", "message": f"confidence {envelope['confidence']:.3f} is below required threshold {float(minimum_confidence):.3f}", "retryable": False, "details": {"threshold": float(minimum_confidence), "verification": options.get("verification", "none")}}
                envelope["trace"].append({"stage": "verification", "mode": options.get("verification", "none"), "status": "rejected", "confidence": envelope["confidence"], "threshold": float(minimum_confidence)})
            elif minimum_confidence is not None and envelope.get("confidence") is None:
                envelope["warnings"].append("confidence threshold could not be evaluated because the provider returned no confidence")
                envelope["trace"].append({"stage": "verification", "mode": options.get("verification", "none"), "status": "unavailable", "threshold": float(minimum_confidence)})
        except WorkerError as exc:
            fallback = self._speech_fallback(canonical, input_path, options, exc)
            if fallback is not None:
                return fallback
            envelope = ResultEnvelope.failure(canonical, provider.name, selected_model, input_info, exc.code, str(exc), retryable=exc.retryable, backend=provider.name).to_dict()
            envelope["performance"] = {"latency_ms": round((time.perf_counter() - started) * 1000), "device": requested_device, "memory_mb": self._memory_mb(), "cached": False, "cold_start": cold_start}
            envelope["trace"] = [{"stage": "routing", **route}, {"stage": "provider", "status": "error", "code": exc.code}]
        except Exception as exc:  # provider isolation: one broken provider never crashes the core
            fallback = self._speech_fallback(canonical, input_path, options, exc)
            if fallback is not None:
                return fallback
            envelope = ResultEnvelope.failure(canonical, provider.name, selected_model, input_info, "provider_error", str(exc), backend=provider.name).to_dict()
            envelope["performance"] = {"latency_ms": round((time.perf_counter() - started) * 1000), "device": requested_device, "memory_mb": self._memory_mb(), "cached": False, "cold_start": cold_start}
            envelope["trace"] = [{"stage": "routing", **route}, {"stage": "provider", "status": "error", "code": "provider_error"}]
        finally:
            self.cache.update_state(canonical, "ready")
        envelope = self._finish(envelope)
        if envelope.get("error") is None:
            try:
                self.cache.write_result(key, envelope)
            except OSError as exc:
                self.logger.emit("cache.write_failed", capability=canonical, error=str(exc))
        return envelope

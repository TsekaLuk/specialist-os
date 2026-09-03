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
from .hardware import detect_hardware, recommended_model
from .models import ModelManager
from .environments import EnvironmentError, ProviderEnvironmentManager, PROVIDER_REQUIREMENTS
from .observability import EventLogger
from .providers import JsonlProcessProvider, WorkerError
from .providers.factory import provider_map
from .registry import BUNDLES, CAPABILITIES, registry_snapshot, resolve_capability
from .rust_core import rust_validate_input
from .schemas import ResultEnvelope, validate_envelope


class SpecialistRuntime:
    TIMEOUTS = {"vision.detect": 120, "vision.segment": 120, "vision.ocr": 120, "vision.depth": 300, "screen.parse": 120, "document.parse": 900, "audio.transcribe": 900, "audio.vad": 300}

    def __init__(self, home=None, provider_overrides=None, isolate=False, backend="auto", with_dependencies=False, max_loaded=4, allow_unverified_models=None):
        self.cache = Cache(home)
        self.backend = backend
        self.with_dependencies = with_dependencies
        self.allow_unverified_models = bool(os.environ.get("SPECIALIST_ALLOW_UNVERIFIED_MODELS") == "1") if allow_unverified_models is None else bool(allow_unverified_models)
        self.max_loaded = max(1, int(max_loaded))
        self.providers = provider_map(backend)
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
        self._last_used: dict[str, float] = {}
        self._locks = {name: threading.RLock() for name in self.providers}
        self._metrics_lock = threading.Lock()
        self.models_manager = ModelManager(self.cache)
        self.environments = ProviderEnvironmentManager(self.cache)
        self.logger = EventLogger(self.cache.home, enabled=True)
        self._metrics = {"requests_total": 0, "errors_total": 0, "cache_hits_total": 0, "latency_ms_total": 0}

    def capabilities(self):
        return registry_snapshot()

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
        worker = JsonlProcessProvider(provider.name, name, provider.model, [str(python), "-m", "specialist", "_worker", "--capability", name, "--backend", self.backend], timeout_seconds=timeout, cpu_limit_seconds=timeout + 10, env={"SPECIALIST_HOME": str(self.cache.home), "PYTHONPATH": pythonpath, "SPECIALIST_ALLOW_UNVERIFIED_MODELS": "1" if self.allow_unverified_models else "0"}, log_path=self.cache.logs / f"{name.replace('.', '__')}.worker.log")
        worker.requires_verified_artifact = bool(getattr(provider, "requires_verified_artifact", False) if requires_verified_artifact is None else requires_verified_artifact)
        return worker

    def metrics(self):
        with self._metrics_lock:
            return dict(self._metrics)

    def readiness(self):
        hardware = detect_hardware()
        capability_states = []
        for spec in CAPABILITIES.values():
            provider = self.providers[spec.name]
            installation = self.cache.installation(spec.name)
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
                            self.models_manager.verify(Path(artifact), digest)
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

    def install(self, target: str, source: str | None = None, sha256: str | None = None, with_dependencies=None) -> list[dict[str, Any]]:
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
                if existing and not source and not install_dependencies:
                    installed.append({"capability": name, "provider": existing.get("provider", spec.provider), "model": existing.get("model", spec.model), "status": existing.get("status", "ready"), "already_installed": True})
                    continue
                selected_model = self._model_for(spec, existing)
                model_spec = spec.model_spec(selected_model)
                provider = self.providers[name]
                if hasattr(provider, "model"):
                    provider.model = selected_model
                dependency_env = None
                try:
                    if install_dependencies and self.backend != "fallback" and spec.optional_dependency in PROVIDER_REQUIREMENTS and PROVIDER_REQUIREMENTS[spec.optional_dependency]:
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
                    if auto_source is None and model_spec.artifact_url and model_spec.artifact_sha256:
                        auto_source = model_spec.artifact_url
                        auto_sha256 = model_spec.artifact_sha256
                    if auto_source:
                        artifact_path = self.cache.models / name.replace(".", "__") / selected_model
                        self.models_manager.ensure_capacity(artifact_path, model_spec.disk_mb * 1024 * 1024)
                        self.cache.mark_installed(name, provider.name, selected_model, status="downloading", license_name=spec.license, source=auto_source, sha256=auto_sha256, artifact_path=artifact_path, commercial=spec.commercial, source_url=spec.source_url)
                        artifact = self.models_manager.download(auto_source, artifact_path, expected_sha256=auto_sha256)
                        self.cache.mark_installed(name, provider.name, selected_model, status="ready", license_name=spec.license, source=auto_source, sha256=artifact["sha256"], artifact_path=artifact_path, commercial=spec.commercial, source_url=spec.source_url)
                        details.update({"artifact": artifact, "verification": "sha256"})
                    installed.append({"capability": name, "provider": spec.provider, "model": selected_model, "environment": dependency_env, "registry_model": {"source_url": spec.source_url, "memory_mb": model_spec.memory_mb, "disk_mb": model_spec.disk_mb, "platforms": list(model_spec.platforms), "devices": list(model_spec.devices), "artifact_url": model_spec.artifact_url, "artifact_sha256": model_spec.artifact_sha256}, **details})
                except Exception as exc:
                    self.cache.mark_error(name, provider.name, selected_model, str(exc), source=source)
                    artifact_path = self.cache.models / name.replace(".", "__") / selected_model
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
            provider = self.providers[spec.name]
            installation = self.cache.installation(spec.name)
            details = provider.doctor(hardware)
            environment = self.environments.status(spec.provider) if spec.optional_dependency in PROVIDER_REQUIREMENTS and PROVIDER_REQUIREMENTS[spec.optional_dependency] else None
            if environment and environment.get("status") == "ready" and not self.environments.verify(spec.provider, PROVIDER_REQUIREMENTS[spec.optional_dependency]):
                environment = {**environment, "status": "corrupt", "message": "provider environment imports are not usable"}
            if fix and self.with_dependencies and self.backend != "fallback" and spec.optional_dependency in PROVIDER_REQUIREMENTS and PROVIDER_REQUIREMENTS[spec.optional_dependency] and environment and environment.get("status") != "ready":
                try:
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
                    digest = self.models_manager.verify(Path(installation["artifact_path"]), installation.get("sha256"))
                    verification = {"status": "verified", "sha256": digest}
                except Exception as exc:
                    verification = {"status": "corrupt", "error": str(exc)}
                    self.cache.update_state(spec.name, "corrupt")
                    if fix:
                        model_spec = spec.model_spec(self._model_for(spec, installation, hardware))
                        if model_spec.artifact_url and model_spec.artifact_sha256:
                            try:
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
            capabilities.append({"capability": spec.name, "provider": spec.provider, "model": self._model_for(spec, installation, hardware), "installation": installation, "error": error_state, "environment": environment, "verification": verification, "registry": {"source_url": spec.source_url, "models": [model.id for model in spec.models]}, **details, "status": state})
        return {"version": "0.2.0", "home": str(self.cache.home), "system": hardware, "capabilities": capabilities, "fixes": fixes, "warnings": warnings}

    def models(self):
        output = []
        for spec in CAPABILITIES.values():
            installation = self.cache.installation(spec.name)
            state = "not installed"
            verification = None
            if installation:
                state = installation.get("status", "ready")
                artifact = installation.get("artifact_path")
                if artifact:
                    try:
                        verification = {"status": "verified", "sha256": self.models_manager.verify(Path(artifact), installation.get("sha256"))}
                    except Exception as exc:
                        state = "corrupt"
                        verification = {"status": "corrupt", "error": str(exc)}
            error_state = self.cache.error_state(spec.name)
            if not installation and error_state:
                state = "error"
            registry_model = spec.model_spec(self._model_for(spec, installation))
            output.append({"capability": spec.name, "provider": spec.provider, "model": self._model_for(spec, installation), "status": state, "installation": installation, "error": error_state, "registry": {"source_url": spec.source_url, "recommended": registry_model.recommended, "memory_mb": registry_model.memory_mb, "disk_mb": registry_model.disk_mb, "platforms": list(registry_model.platforms), "devices": list(registry_model.devices), "artifact_url": registry_model.artifact_url, "artifact_sha256": registry_model.artifact_sha256}, "verification": verification})
        return output

    def remove_model(self, target):
        names = BUNDLES.get(target.lower(), [resolve_capability(target)])
        output = []
        for name in names:
            with self._locks[name]:
                if name in self._loaded:
                    self.providers[name].unload()
                    self._loaded.discard(name)
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

    def close(self):
        for name in list(self._loaded):
            try:
                self.providers[name].unload()
                self.cache.update_state(name, "unloaded")
            finally:
                self._loaded.discard(name)
                self._last_used.pop(name, None)

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
        try:
            self.providers[victim].unload()
            self.cache.update_state(victim, "unloaded")
        finally:
            self._loaded.discard(victim)
            self._last_used.pop(victim, None)

    def run(self, capability: str, input_path: str | Path, options: dict[str, Any] | None = None) -> dict[str, Any]:
        canonical = resolve_capability(capability)
        with self._locks[canonical]:
            return self._run(capability, input_path, options)

    def _finish(self, envelope: dict[str, Any]) -> dict[str, Any]:
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
        requested_device = options.get("device", "cpu")
        if requested_device not in getattr(provider, "supported_devices", ("cpu",)):
            return self._finish(ResultEnvelope.failure(canonical, spec.provider, spec.model, input_info, "invalid_options", f"device must be one of {list(getattr(provider, 'supported_devices', ('cpu',)))}").to_dict())
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
        installation = self.cache.installation(canonical)
        selected_model = self._model_for(spec, installation)
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
                    self.install(canonical, with_dependencies=True)
                    provider = self.providers[canonical]
                    installation = self.cache.installation(canonical)
                    selected_model = self._model_for(spec, installation)
                else:
                    self.install(canonical, with_dependencies=False)
                    provider = self.providers[canonical]
                    installation = self.cache.installation(canonical)
                    selected_model = self._model_for(spec, installation)
                if hasattr(provider, "model"):
                    provider.model = selected_model
            except WorkerError as exc:
                return self._finish(ResultEnvelope.failure(canonical, spec.provider, spec.model, input_info, exc.code, str(exc), retryable=exc.retryable).to_dict())
            except Exception as exc:
                return self._finish(ResultEnvelope.failure(canonical, spec.provider, spec.model, input_info, "provider_install_failed", str(exc), retryable=False).to_dict())
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
            envelope = ResultEnvelope(canonical, provider.name, selected_model, input_info, result=result, performance={"latency_ms": round((time.perf_counter() - started) * 1000), "device": requested_device, "memory_mb": self._memory_mb(), "cached": False, "cold_start": cold_start}, warnings=warnings).to_dict()
        except WorkerError as exc:
            envelope = ResultEnvelope.failure(canonical, provider.name, selected_model, input_info, exc.code, str(exc), retryable=exc.retryable, backend=provider.name).to_dict()
            envelope["performance"] = {"latency_ms": round((time.perf_counter() - started) * 1000), "device": requested_device, "memory_mb": self._memory_mb(), "cached": False, "cold_start": cold_start}
        except Exception as exc:  # provider isolation: one broken provider never crashes the core
            envelope = ResultEnvelope.failure(canonical, provider.name, selected_model, input_info, "provider_error", str(exc), backend=provider.name).to_dict()
            envelope["performance"] = {"latency_ms": round((time.perf_counter() - started) * 1000), "device": requested_device, "memory_mb": self._memory_mb(), "cached": False, "cold_start": cold_start}
        finally:
            self.cache.update_state(canonical, "ready")
        envelope = self._finish(envelope)
        if envelope.get("error") is None:
            try:
                self.cache.write_result(key, envelope)
            except OSError as exc:
                self.logger.emit("cache.write_failed", capability=canonical, error=str(exc))
        return envelope

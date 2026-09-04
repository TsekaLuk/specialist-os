"""Provider isolation over a persistent JSON Lines worker.

The worker stays warm after the first request for low latency, while every
provider still has a strict process boundary, serialized requests and a hard
timeout. A crashed or timed-out worker is terminated before the next request.
"""

from __future__ import annotations

import json
import contextlib
import io
import os
import queue
import signal
import subprocess
import threading
from pathlib import Path
from typing import Any, Sequence


class WorkerError(RuntimeError):
    def __init__(self, message, code="worker_error", retryable=True):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class JsonlProcessProvider:
    """Adapt any provider worker command to the Provider protocol."""

    def __init__(self, name, capability, model, command: Sequence[str], *, timeout_seconds=120, max_output_bytes=8 * 1024 * 1024, max_request_bytes=1 * 1024 * 1024, memory_limit_bytes=4 * 1024**3, cpu_limit_seconds=None, env=None, log_path=None):
        self.name = name
        self.capability = capability
        self.model = model
        self.command = list(command)
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes
        self.max_request_bytes = max_request_bytes
        self.memory_limit_bytes = memory_limit_bytes
        self.cpu_limit_seconds = cpu_limit_seconds
        self.env = env or {}
        self.log_path = Path(log_path) if log_path else None
        self._stderr_stream = None
        self.supported_platforms = ("macos-arm64", "linux-x64", "windows-x64")
        self.supported_devices = ("cpu", "mps", "cuda")
        self.memory_requirement_mb = 512
        self.disk_requirement_mb = 0
        self.license = "provider terms"
        self.requires_verified_artifact = False
        self.requires_local_model_directory = False
        self._process = None
        self._responses = queue.Queue()
        self._reader_thread = None
        self._io_lock = threading.RLock()

    def install(self, cache, spec):
        if not self.command:
            raise WorkerError("worker command is empty", code="worker_not_configured", retryable=False)
        model = getattr(self, "model", None) or spec.model
        cache.mark_installed(spec.name, self.name, model, license_name=getattr(self, "license", spec.license), source="worker", commercial=getattr(spec, "commercial", None), source_url=getattr(spec, "source_url", None))
        return {"status": "ready", "downloaded": False, "worker": self.command[0]}

    def doctor(self, hardware):
        executable = self.command[0] if self.command else ""
        path = self.env.get("PATH", os.environ.get("PATH", ""))
        path_entries = path.split(os.pathsep)
        available = bool(executable and (Path(executable).exists() or any(Path(item, executable).exists() for item in path_entries)))
        details = {"status": "ready" if available else "not ready", "backend": "isolated-worker", "worker": executable, "memory_limit_bytes": self.memory_limit_bytes, "cpu_limit_seconds": self.cpu_limit_seconds, "hardware": hardware}
        if available and self.requires_local_model_directory:
            model_dir = self.env.get("SPECIALIST_MINERU_MODEL_DIR") or os.environ.get("SPECIALIST_MINERU_MODEL_DIR")
            if not model_dir or not Path(model_dir).expanduser().is_dir() or not any(Path(model_dir).expanduser().iterdir()):
                details.update({"status": "not ready", "error": {"code": "model_directory_required", "message": "MinerU pipeline models require SPECIALIST_MINERU_MODEL_DIR"}})
        return details

    def load(self):
        with self._io_lock:
            if self._process is None or self._process.poll() is not None:
                try:
                    self._start_worker()
                except OSError as exc:
                    raise WorkerError(f"could not start provider worker: {exc}", code="worker_start_failed", retryable=False) from exc
        return self

    def unload(self):
        with self._io_lock:
            self._stop_worker()
        return None

    def _start_worker(self):
        environment = os.environ.copy()
        environment.update(self.env)
        stderr = subprocess.DEVNULL
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            if self.log_path.exists() and self.log_path.stat().st_size > 10 * 1024 * 1024:
                rotated = self.log_path.with_suffix(self.log_path.suffix + ".1")
                rotated.unlink(missing_ok=True)
                self.log_path.replace(rotated)
            self._stderr_stream = self.log_path.open("a", encoding="utf-8")
            stderr = self._stderr_stream
        popen_kwargs = {"stdin": subprocess.PIPE, "stdout": subprocess.PIPE, "stderr": stderr, "text": True, "bufsize": 1, "env": environment}
        if os.name == "posix":
            popen_kwargs["start_new_session"] = True
        if os.name == "posix" and (self.memory_limit_bytes or self.cpu_limit_seconds):
            def apply_limits():
                import resource

                try:
                    if self.memory_limit_bytes:
                        _, hard = resource.getrlimit(resource.RLIMIT_AS)
                        limit = self.memory_limit_bytes if hard == resource.RLIM_INFINITY else min(self.memory_limit_bytes, hard)
                        resource.setrlimit(resource.RLIMIT_AS, (limit, hard))
                    if self.cpu_limit_seconds:
                        _, hard = resource.getrlimit(resource.RLIMIT_CPU)
                        limit = self.cpu_limit_seconds if hard == resource.RLIM_INFINITY else min(self.cpu_limit_seconds, hard)
                        resource.setrlimit(resource.RLIMIT_CPU, (limit, hard))
                except (OSError, ValueError):
                    # Some macOS launch contexts disallow RLIMIT_AS. The
                    # worker remains isolated and wall-clock limited.
                    return

            popen_kwargs["preexec_fn"] = apply_limits
        try:
            self._process = subprocess.Popen(self.command, **popen_kwargs)
        except OSError:
            if self._stderr_stream:
                self._stderr_stream.close()
                self._stderr_stream = None
            self._process = None
            raise
        self._responses = queue.Queue()

        def read_responses(process, responses):
            try:
                for line in process.stdout:
                    responses.put(line)
                responses.put(EOFError(f"worker exited with code {process.poll()}"))
            except (OSError, ValueError) as exc:
                responses.put(exc)

        self._reader_thread = threading.Thread(target=read_responses, args=(self._process, self._responses), daemon=True)
        self._reader_thread.start()

    def _stop_worker(self):
        process, self._process = self._process, None
        if process is None:
            return
        if process.poll() is None:
            try:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGTERM)
                else:
                    process.terminate()
                process.wait(timeout=0.5)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    if os.name == "posix":
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                except OSError:
                    pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        # Closing the parent pipe is what unblocks a reader that is waiting in
        # ``for line in process.stdout`` after the child has exited. Do this
        # before joining so interpreter shutdown cannot leave a daemon thread
        # holding a BufferedReader lock.
        for stream in (process.stdin, process.stdout):
            try:
                if stream:
                    stream.close()
            except OSError:
                pass
        reader = self._reader_thread
        if reader is not None and reader is not threading.current_thread():
            reader.join(timeout=2)
        self._reader_thread = None
        if self._stderr_stream:
            try:
                self._stderr_stream.close()
            except OSError:
                pass
            self._stderr_stream = None

    def infer(self, input_path: Path, options: dict[str, Any], cache):
        request = {"capability": self.capability, "provider": self.name, "model": self.model, "input_path": str(input_path), "options": options}
        encoded_request = json.dumps(request, ensure_ascii=True, separators=(",", ":")) + "\n"
        if len(encoded_request.encode("utf-8")) > self.max_request_bytes:
            raise WorkerError("provider worker request exceeds safety limit", code="worker_request_too_large", retryable=False)
        with self._io_lock:
            self.load()
            try:
                self._process.stdin.write(encoded_request)
                self._process.stdin.flush()
            except (OSError, AttributeError) as exc:
                self._stop_worker()
                raise WorkerError(f"could not send request to provider worker: {exc}", code="worker_write_failed") from exc
            try:
                try:
                    timeout = min(float(options.get("timeout_seconds", self.timeout_seconds)), float(self.timeout_seconds))
                except (TypeError, ValueError):
                    timeout = float(self.timeout_seconds)
                timeout = max(0.001, timeout)
                response_line = self._responses.get(timeout=timeout)
            except queue.Empty as exc:
                self._stop_worker()
                raise WorkerError(f"provider worker timed out after {timeout}s", code="provider_timeout") from exc
            if isinstance(response_line, Exception):
                self._stop_worker()
                raise WorkerError(f"provider worker stream failed: {response_line}", code="worker_stream_failed") from response_line
            if len(response_line.encode("utf-8", errors="replace")) > self.max_output_bytes:
                self._stop_worker()
                raise WorkerError("provider worker output exceeds safety limit", code="worker_output_too_large", retryable=False)
            if not isinstance(response_line, str):
                self._stop_worker()
                raise WorkerError("provider worker returned a non-text response", code="worker_invalid_output", retryable=False)
            try:
                response = json.loads(response_line)
            except ValueError as exc:
                self._stop_worker()
                raise WorkerError("provider worker returned invalid JSON", code="worker_invalid_output", retryable=False) from exc
            if not isinstance(response, dict):
                self._stop_worker()
                raise WorkerError("provider worker returned a JSON value instead of an object", code="worker_invalid_output", retryable=False)
            if response.get("error"):
                error = response["error"]
                raise WorkerError(error.get("message", "provider worker failed"), code=error.get("code", "provider_error"), retryable=bool(error.get("retryable", False)))
            return response.get("result", {}), response.get("warnings", [])


def run_worker(request: dict[str, Any], backend="fallback", providers=None) -> dict[str, Any]:
    """Worker entrypoint for fallback or optional production providers."""
    from .factory import provider_map

    capability = request.get("capability")
    providers = providers if providers is not None else provider_map(backend)
    provider = providers.get(capability)
    requested_provider = request.get("provider")
    if isinstance(requested_provider, str) and requested_provider:
        provider = next((candidate for candidate in providers.values() if getattr(candidate, "name", None) == requested_provider and getattr(candidate, "capability", capability) == capability), provider)
    if provider is None:
        return {"error": {"code": "unknown_capability", "message": str(capability), "retryable": False}}
    try:
        worker_cache = _WorkerCache()
        provider._cache = worker_cache
        requested_model = request.get("model")
        if isinstance(requested_model, str) and requested_model:
            provider.model = requested_model
        installation = worker_cache.installation(capability)
        if installation and installation.get("artifact_path"):
            provider.model = installation["artifact_path"]
        # Provider libraries commonly print progress bars and diagnostics to
        # stdout. The JSONL protocol owns stdout, so capture both streams at
        # the process boundary to prevent log bytes corrupting a response.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result, warnings = provider.infer(Path(request["input_path"]), request.get("options") or {}, worker_cache)
        return {"result": result, "warnings": warnings}
    except WorkerError as exc:
        return {"error": {"code": exc.code, "message": str(exc), "retryable": exc.retryable}}
    except Exception as exc:
        return {"error": {"code": "provider_error", "message": str(exc), "retryable": False}}


def run_builtin_worker(request: dict[str, Any]) -> dict[str, Any]:
    """Backward-compatible alias for the dependency-free worker."""
    return run_worker(request, backend="fallback")


class _WorkerCache:
    home = Path(os.environ.get("SPECIALIST_HOME", Path.home() / ".specialist"))
    models = home / "models"
    results = home / "cache" / "results"
    artifacts = home / "artifacts"
    metadata = home / "metadata"

    def ensure_dirs(self):
        self.results.mkdir(parents=True, exist_ok=True)

    def input_hash(self, path):
        import hashlib

        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def installation(self, capability):
        marker = self.metadata / (capability.replace(".", "__") + ".json")
        try:
            return json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

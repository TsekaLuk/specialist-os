"""Fish Audio server lifecycle and readiness state."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import tempfile
import time
from typing import Any

from .client import FishAudioClient, FishAudioError


class FishAudioLifecycle:
    def __init__(self, client: FishAudioClient, *, command: str | None = None, start_policy: str = "on-demand", startup_timeout: float = 180, state_path: str | Path | None = None):
        if start_policy not in {"manual", "on-demand", "always-on"}:
            raise ValueError("Fish Audio start_policy must be manual, on-demand or always-on")
        self.client = client
        self.command = command or os.environ.get("SPECIALIST_FISH_AUDIO_COMMAND")
        self.start_policy = start_policy
        self.startup_timeout = float(startup_timeout)
        self.state_path = Path(state_path).expanduser() if state_path is not None else Path.home() / ".specialist" / "metadata" / "fish_audio.lifecycle.json"
        self.process: subprocess.Popen | None = None
        self._process_new_session = False
        self.state = "STOPPED"

    def _read_persistent_state(self) -> dict[str, Any] | None:
        if self.state_path.is_symlink() or not self.state_path.is_file():
            return None
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(value, dict) or value.get("endpoint") != self.client.endpoint:
            return None
        pid = value.get("pid")
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
            return None
        return value

    def _write_persistent_state(self, pid: int) -> None:
        if self.state_path.is_symlink():
            raise FishAudioError("Fish Audio lifecycle state cannot be a symlink", code="fish_audio_state_invalid", retryable=False)
        self.state_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self.state_path.parent.chmod(0o700)
        except OSError:
            pass
        payload = {"pid": int(pid), "endpoint": self.client.endpoint, "started_at": time.time()}
        temporary = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.state_path.parent, prefix=f".{self.state_path.name}.", delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(payload, stream, ensure_ascii=True, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.state_path)
            try:
                self.state_path.chmod(0o600)
            except OSError:
                pass
        finally:
            if temporary and temporary.exists():
                temporary.unlink(missing_ok=True)

    def _clear_persistent_state(self) -> None:
        try:
            if self.state_path.is_symlink():
                raise FishAudioError("Fish Audio lifecycle state cannot be a symlink", code="fish_audio_state_invalid", retryable=False)
            self.state_path.unlink(missing_ok=True)
        except OSError:
            pass

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except (ProcessLookupError, PermissionError):
            return False
        except OSError:
            return False
        return True

    def health(self, timeout: float = 1.5) -> dict[str, Any]:
        persistent = self._read_persistent_state()
        try:
            value = self.client.health(timeout=timeout)
        except FishAudioError as exc:
            if persistent and not self._pid_alive(persistent["pid"]):
                self._clear_persistent_state()
                persistent = None
            self.state = "UNHEALTHY" if self.process is not None or persistent else "STOPPED"
            return {"status": "not ready", "state": self.state, "endpoint": self.client.endpoint, "pid": self.process.pid if self.process else (persistent or {}).get("pid"), "error": {"code": exc.code, "message": str(exc)}}
        self.state = "READY"
        return {"status": "ready", "state": self.state, "server": value, "endpoint": self.client.endpoint, "pid": self.process.pid if self.process else (persistent or {}).get("pid"), "persistent": bool(persistent)}

    def start(self, *, persist: bool = False) -> dict[str, Any]:
        current = self.health()
        if current.get("status") == "ready":
            return {**current, "started": False, "persistent": bool(current.get("persistent") or persist)}
        if self.process is not None and self.process.poll() is not None:
            self.process = None
        if self.process is None:
            persistent = self._read_persistent_state()
            if persistent and self._pid_alive(persistent["pid"]):
                self.state = "STARTING"
            elif not self.command:
                self.state = "UNHEALTHY"
                raise FishAudioError("Fish Audio server is unavailable and SPECIALIST_FISH_AUDIO_COMMAND is not configured", code="fish_audio_start_not_configured", retryable=False)
            else:
                argv = [item.replace("{endpoint}", self.client.endpoint) for item in shlex.split(self.command)]
                if not argv:
                    raise FishAudioError("SPECIALIST_FISH_AUDIO_COMMAND is empty", code="fish_audio_start_not_configured", retryable=False)
                environment = os.environ.copy()
                environment.setdefault("SPECIALIST_FISH_AUDIO_URL", self.client.endpoint)
                try:
                    kwargs = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "env": environment}
                    if os.name == "posix":
                        # Request-scoped servers stay in the worker/runtime
                        # process group so an abrupt worker shutdown reaps
                        # them. Explicit lifecycle starts use a new session
                        # and are supervised by the persistent PID state.
                        self._process_new_session = bool(persist)
                        kwargs["start_new_session"] = self._process_new_session
                    self.process = subprocess.Popen(argv, **kwargs)
                except OSError as exc:
                    self.state = "UNHEALTHY"
                    raise FishAudioError(f"could not start Fish Audio server: {exc}", code="fish_audio_start_failed", retryable=False) from exc
            self.state = "STARTING"
        else:
            self.state = "STARTING"
        deadline = time.monotonic() + self.startup_timeout
        while time.monotonic() < deadline:
            if self.process is not None and self.process.poll() is not None:
                self.state = "UNHEALTHY"
                raise FishAudioError(f"Fish Audio server exited with code {self.process.returncode}", code="fish_audio_process_exit", retryable=False)
            current = self.health()
            if current.get("status") == "ready":
                if persist and self.process is not None:
                    detached = self.process
                    self._write_persistent_state(detached.pid)
                    # The server has its own session and is now supervised by
                    # the PID state file. Mark the local Popen handle as
                    # detached before releasing it so interpreter teardown
                    # does not emit a false ResourceWarning.
                    detached.returncode = 0
                    self.process = None
                return {**current, "started": True, "persistent": bool(persist or current.get("persistent"))}
            time.sleep(0.5)
        self.state = "UNHEALTHY"
        raise FishAudioError(f"Fish Audio server did not become ready within {self.startup_timeout:g}s", code="fish_audio_start_timeout", retryable=True)

    def ensure_ready(self) -> dict[str, Any]:
        current = self.health()
        if current.get("status") == "ready":
            return current
        if self.start_policy == "manual":
            raise FishAudioError("Fish Audio server is not ready; start it manually", code="fish_audio_not_ready", retryable=True)
        return self.start(persist=self.start_policy == "always-on")

    def stop(self) -> dict[str, Any]:
        process, self.process = self.process, None
        persistent = self._read_persistent_state()
        pid = process.pid if process is not None else (persistent or {}).get("pid")
        if process is not None:
            if process.poll() is None:
                try:
                    if os.name == "posix" and self._process_new_session:
                        os.killpg(process.pid, signal.SIGTERM)
                    else:
                        process.terminate()
                    process.wait(timeout=5)
                except (OSError, subprocess.TimeoutExpired):
                    try:
                        if os.name == "posix" and self._process_new_session:
                            os.killpg(process.pid, signal.SIGKILL)
                        else:
                            process.kill()
                    except OSError:
                        pass
        elif isinstance(pid, int) and self._pid_alive(pid):
            try:
                if os.name == "posix":
                    os.killpg(pid, signal.SIGTERM)
                else:
                    os.kill(pid, signal.SIGTERM)
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline and self._pid_alive(pid):
                    try:
                        self.client.health(timeout=0.2)
                    except FishAudioError:
                        # A detached child may be re-parented and remain a
                        # zombie briefly; endpoint readiness is the useful
                        # service-level stop signal in that case.
                        break
                    time.sleep(0.05)
                if self._pid_alive(pid):
                    if os.name == "posix":
                        os.killpg(pid, signal.SIGKILL)
                    else:
                        os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        self._clear_persistent_state()
        self.state = "STOPPED"
        return {"status": "stopped", "state": self.state, "endpoint": self.client.endpoint}

    def restart(self, *, persist: bool = False) -> dict[str, Any]:
        self.stop()
        return self.start(persist=persist)

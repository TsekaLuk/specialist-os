"""Small standard-library helpers for process-boundary E2E tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[2]


def test_environment(home: Path | None = None, **overrides: str) -> dict[str, str]:
    environment = os.environ.copy()
    existing_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = str(ROOT) if not existing_pythonpath else str(ROOT) + os.pathsep + existing_pythonpath
    environment.pop("SPECIALIST_API_TOKEN", None)
    if home is not None:
        environment["SPECIALIST_HOME"] = str(home)
    environment.update({key: value for key, value in overrides.items() if value is not None})
    return environment


def run_cli(arguments: list[str], home: Path, *, timeout: float = 30, **environment_overrides: str) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, "-m", "specialist", "--home", str(home), *arguments]
    return subprocess.run(
        command,
        cwd=ROOT,
        env=test_environment(home, **environment_overrides),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class LineReader:
    """Read a subprocess text stream without allowing tests to hang forever."""

    def __init__(self, stream):
        self._lines: queue.Queue[str | BaseException] = queue.Queue()
        self._stream = stream
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()

    def _read(self):
        try:
            for line in self._stream:
                self._lines.put(line)
        except BaseException as exc:  # surfaced to the test that consumes it
            self._lines.put(exc)
        finally:
            self._lines.put(EOFError("stream closed"))

    def get(self, timeout: float = 5) -> str:
        value = self._lines.get(timeout=timeout)
        if isinstance(value, BaseException):
            raise value
        return value

    def join(self, timeout: float = 1):
        self._thread.join(timeout=timeout)


class HttpService:
    """Run the real ``specialist serve`` process on a temporary port."""

    def __init__(self, home: Path, *, token: str | None = None, max_request_bytes: int = 1024 * 1024):
        self.home = home
        self.token = token
        self.max_request_bytes = max_request_bytes
        self.port = free_port()
        self.process: subprocess.Popen[str] | None = None
        self.stdout: LineReader | None = None
        self.stderr: LineReader | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self):
        command = [
            sys.executable,
            "-m",
            "specialist",
            "--home",
            str(self.home),
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            str(self.port),
            "--max-request-bytes",
            str(self.max_request_bytes),
        ]
        if self.token:
            command.extend(["--token", self.token])
        self.process = subprocess.Popen(
            command,
            cwd=ROOT,
            env=test_environment(self.home),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self.stdout = LineReader(self.process.stdout)
        self.stderr = LineReader(self.process.stderr)
        try:
            announcement = self.stdout.get(timeout=5)
            if "listening" not in announcement:
                raise RuntimeError(f"server did not start: {announcement!r}")
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                try:
                    status, _, _ = http_request(f"{self.url}/health", timeout=0.5)
                    if status == 200:
                        return self
                except (OSError, urllib.error.URLError):
                    time.sleep(0.05)
            raise RuntimeError("server did not become healthy")
        except BaseException:
            self.close()
            raise

    def close(self):
        process = self.process
        self.process = None
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
        for reader in (self.stdout, self.stderr):
            if reader:
                reader.join()
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream:
                stream.close()

    def __enter__(self):
        return self.start()

    def __exit__(self, _exc_type, _exc, _tb):
        self.close()


def http_request(url: str, *, method: str = "GET", payload=None, raw_body: bytes | None = None, headers: dict[str, str] | None = None, timeout: float = 5) -> tuple[int, dict[str, str], bytes]:
    request_headers = dict(headers or {})
    data = None
    if payload is not None and raw_body is not None:
        raise ValueError("payload and raw_body are mutually exclusive")
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    elif raw_body is not None:
        data = raw_body
    request = urllib.request.Request(url, data=data, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, dict(response.headers.items()), response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read()
        exc.close()
        return exc.code, dict(exc.headers.items()), body


class McpProcess:
    """Drive the real MCP stdio server using JSON Lines."""

    def __init__(self, home: Path):
        self.home = home
        self.process: subprocess.Popen[str] | None = None
        self.stdout: LineReader | None = None
        self.stderr: LineReader | None = None

    def start(self):
        self.process = subprocess.Popen(
            [sys.executable, "-m", "specialist", "--home", str(self.home), "serve", "--mcp"],
            cwd=ROOT,
            env=test_environment(self.home),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self.stdout = LineReader(self.process.stdout)
        self.stderr = LineReader(self.process.stderr)
        return self

    def send(self, request: dict):
        self.send_raw(json.dumps(request, ensure_ascii=True))

    def send_raw(self, line: str):
        if self.process is None or self.process.stdin is None:
            raise RuntimeError("MCP process is not running")
        self.process.stdin.write(line.rstrip("\n") + "\n")
        self.process.stdin.flush()

    def response(self, timeout: float = 5) -> dict:
        if self.stdout is None:
            raise RuntimeError("MCP process is not running")
        return json.loads(self.stdout.get(timeout=timeout))

    def close(self):
        process = self.process
        self.process = None
        if process is None:
            return
        if process.poll() is None and process.stdin:
            process.stdin.close()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        for reader in (self.stdout, self.stderr):
            if reader:
                reader.join()
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream:
                stream.close()

    def __enter__(self):
        return self.start()

    def __exit__(self, _exc_type, _exc, _tb):
        self.close()

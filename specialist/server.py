"""Dependency-free local HTTP and MCP transports."""

from __future__ import annotations

import json
import hmac
import os
import signal
import sys
import threading
import base64
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .registry import CAPABILITIES


def _tool_schema(capability):
    spec = CAPABILITIES[capability]
    return {
        "name": spec.name.replace(".", "_"),
        "description": spec.description,
        "inputSchema": dict(spec.input_schema) or {"type": "object", "properties": {"path": {"type": "string", "description": "Local input file path"}, "options": {"type": "object"}}, "required": ["path"]},
    }


class RuntimeRequestHandler(BaseHTTPRequestHandler):
    runtime = None
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(30)

    def log_message(self, format, *args):
        return

    def _send(self, status, payload):
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            return

    def _send_text(self, status, body, content_type="text/plain; version=0.0.4"):
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(encoded)
        except (BrokenPipeError, ConnectionResetError):
            return

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        route = urlsplit(self.path).path
        if route == "/health":
            from . import __version__

            return self._send(200, {"status": "ok", "version": __version__})
        if not self._authorized():
            return self._send(401, {"error": {"code": "unauthorized", "message": "Bearer token required"}})
        if route in {"/v1/capabilities", "/capabilities"}:
            return self._send(200, {"capabilities": self.runtime.capabilities()})
        if route in {"/v1/providers", "/providers"}:
            return self._send(200, {"providers": self.runtime.provider_manifests()})
        if route in {"/v1/benchmarks", "/benchmarks"}:
            return self._send(200, {"benchmarks": self.runtime.benchmarks.list()})
        if route in {"/v1/packs", "/packs"}:
            return self._send(200, {"packs": self.runtime.packs()})
        if route in {"/v1/studio", "/studio"}:
            from .studio import snapshot

            return self._send(200, snapshot(self.runtime))
        if route.startswith("/v1/routing/"):
            capability = route.removeprefix("/v1/routing/").replace("/", ".")
            try:
                return self._send(200, self.runtime.explain(capability))
            except (KeyError, ValueError) as exc:
                return self._send(404, {"error": {"code": "unknown_capability", "message": str(exc)}})
        if route in {"/ready", "/v1/ready"}:
            readiness = self.runtime.readiness()
            return self._send(200 if readiness.get("status") == "ready" else 503, readiness)
        if route in {"/metrics", "/v1/metrics"}:
            metrics = self.runtime.metrics()
            return self._send_text(200, "\n".join(f"specialist_{key} {value}" for key, value in metrics.items()) + "\n")
        self._send(404, {"error": {"code": "not_found", "message": "Unknown endpoint"}})

    def do_POST(self):
        if not self._authorized():
            return self._send(401, {"error": {"code": "unauthorized", "message": "Bearer token required"}})
        semaphore = getattr(self.server, "request_semaphore", None)
        if semaphore is not None and not semaphore.acquire(blocking=False):
            return self._send(429, {"error": {"code": "busy", "message": "Runtime concurrency limit reached", "retryable": True}})
        try:
            return self._do_post()
        finally:
            if semaphore is not None:
                semaphore.release()

    def _authorized(self):
        expected = getattr(self.server, "api_token", None)
        if not expected:
            return True
        supplied = self.headers.get("Authorization", "")
        if supplied.lower().startswith("bearer "):
            supplied = supplied[7:].strip()
        else:
            supplied = self.headers.get("X-Specialist-Token", "")
        return bool(supplied) and hmac.compare_digest(supplied, expected)

    def _do_post(self):
        route = urlsplit(self.path).path
        if not route.startswith("/v1/"):
            return self._send(404, {"error": {"code": "not_found", "message": "Unknown endpoint"}})
        try:
            if self.headers.get("Transfer-Encoding"):
                return self._send(411, {"error": {"code": "length_required", "message": "chunked request bodies are not supported"}})
            raw_length = self.headers.get("Content-Length")
            if raw_length is None:
                return self._send(411, {"error": {"code": "length_required", "message": "Content-Length is required"}})
            length = int(raw_length)
            max_request_bytes = getattr(self.server, "max_request_bytes", 1024 * 1024)
            if length < 0 or length > max_request_bytes:
                return self._send(413, {"error": {"code": "request_too_large", "message": f"Request exceeds {max_request_bytes} bytes"}})
            content_type = self.headers.get_content_type()
            if length and content_type != "application/json" and not content_type.endswith("+json"):
                return self._send(415, {"error": {"code": "unsupported_media_type", "message": "Content-Type must be application/json"}})
            body = self.rfile.read(length)
            if len(body) != length:
                return self._send(400, {"error": {"code": "incomplete_request", "message": "request body ended before Content-Length"}})
            payload = json.loads(body or b"{}")
            if not isinstance(payload, dict):
                return self._send(400, {"error": {"code": "invalid_request", "message": "JSON body must be an object"}})
            endpoint = route.removeprefix("/v1/").strip("/").replace("/", ".")
            capability = endpoint if endpoint in CAPABILITIES else endpoint.replace("_", ".")
            if capability not in CAPABILITIES:
                return self._send(404, {"error": {"code": "unknown_capability", "message": endpoint}})
            path = payload.get("path") or payload.get("input")
            temporary = None
            if not isinstance(path, str) and isinstance(payload.get("data_base64"), str):
                try:
                    raw = base64.b64decode(payload["data_base64"], validate=True)
                except (ValueError, TypeError) as exc:
                    return self._send(400, {"error": {"code": "invalid_input", "message": f"data_base64 is invalid: {exc}"}})
                if len(raw) > min(getattr(self.server, "max_request_bytes", 1024 * 1024) * 3 // 4, 512 * 1024 * 1024):
                    return self._send(413, {"error": {"code": "request_too_large", "message": "decoded input exceeds the request limit"}})
                suffix = Path(str(payload.get("filename") or "input.bin")).suffix
                self.runtime.cache.ensure_dirs()
                temporary = tempfile.NamedTemporaryFile(prefix="specialist-remote-", suffix=suffix, dir=self.runtime.cache.home, delete=False)
                temporary.write(raw)
                temporary.close()
                path = temporary.name
            if not isinstance(path, str):
                return self._send(400, {"error": {"code": "invalid_request", "message": "JSON body requires a string 'path' or data_base64"}})
            try:
                response = self.runtime.run(capability, path, payload.get("options") or {})
            finally:
                if temporary is not None:
                    Path(temporary.name).unlink(missing_ok=True)
            return self._send(200 if response.get("error") is None else 422, response)
        except (ValueError, json.JSONDecodeError) as exc:
            self._send(400, {"error": {"code": "invalid_json", "message": str(exc)}})
        except Exception as exc:
            self._send(500, {"error": {"code": "internal_error", "message": str(exc), "retryable": True}})


def serve_http(runtime, host="127.0.0.1", port=8741, token=None, max_concurrency=4, max_request_bytes=1024 * 1024):
    token = token or os.environ.get("SPECIALIST_API_TOKEN")
    if host not in {"127.0.0.1", "localhost", "::1"} and not token:
        raise ValueError("Refusing non-loopback bind without SPECIALIST_API_TOKEN or --token")
    if not 0 <= int(port) <= 65535:
        raise ValueError("port must be between 0 and 65535")
    if max_concurrency <= 0:
        raise ValueError("max_concurrency must be positive")
    if max_request_bytes <= 0:
        raise ValueError("max_request_bytes must be positive")
    handler = type("SpecialistRequestHandler", (RuntimeRequestHandler,), {"runtime": runtime})
    server = ThreadingHTTPServer((host, port), handler)
    server.api_token = token
    server.max_request_bytes = max_request_bytes
    server.request_semaphore = threading.BoundedSemaphore(max(1, max_concurrency))
    print(f"Specialist Runtime HTTP listening on http://{host}:{port}", flush=True)
    try:
        previous = {name: signal.getsignal(name) for name in (signal.SIGTERM, signal.SIGINT)}
    except ValueError:
        previous = {}

    def stop(_signum, _frame):
        threading.Thread(target=server.shutdown, daemon=True).start()

    if previous:
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
    try:
        server.serve_forever()
    finally:
        for name, handler in previous.items():
            signal.signal(name, handler)
        server.server_close()
        runtime.close()


def serve_mcp(runtime, max_request_bytes=4 * 1024 * 1024):
    """Serve the MCP JSON-RPC subset over stdin/stdout.

    MCP clients need initialize, tools/list and tools/call for the core runtime.
    Notifications are acknowledged silently and malformed requests receive a
    JSON-RPC error without terminating the process.
    """
    previous = signal.getsignal(signal.SIGTERM)

    def stop_mcp(_signum, _frame):
        raise KeyboardInterrupt()

    signal.signal(signal.SIGTERM, stop_mcp)
    try:
        try:
            for line in sys.stdin:
                request_id = None
                is_notification = False
                try:
                    if len(line.encode("utf-8", errors="replace")) > max_request_bytes:
                        raise ValueError(f"MCP request exceeds {max_request_bytes} bytes")
                    request = json.loads(line)
                    if not isinstance(request, dict):
                        raise ValueError("JSON-RPC request must be an object")
                    request_id = request.get("id")
                    if request.get("jsonrpc") not in {None, "2.0"}:
                        raise ValueError("jsonrpc must be 2.0")
                    method = request.get("method")
                    is_notification = "id" not in request
                    if method == "initialize":
                        from . import __version__

                        result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "specialist-runtime", "version": __version__}}
                    elif method == "notifications/initialized":
                        continue
                    elif method == "tools/list":
                        result = {"tools": [_tool_schema(name) for name in CAPABILITIES]}
                    elif method == "tools/call":
                        params = request.get("params") or {}
                        tool_name = params.get("name", "").replace("_", ".")
                        capability = tool_name if tool_name in CAPABILITIES else next((name for name in CAPABILITIES if name.replace(".", "_") == params.get("name")), None)
                        arguments = params.get("arguments") or {}
                        if capability not in CAPABILITIES or not isinstance(arguments.get("path"), str):
                            raise ValueError("tools/call requires a known tool and string arguments.path")
                        value = runtime.run(capability, arguments["path"], arguments.get("options") or {})
                        result = {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=True)}], "structuredContent": value, "isError": value.get("error") is not None}
                    else:
                        if is_notification:
                            continue
                        raise ValueError(f"Method not found: {method}")
                    if request_id is not None:
                        print(json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}, ensure_ascii=True), flush=True)
                except Exception as exc:
                    if is_notification:
                        continue
                    error_code = -32700 if isinstance(exc, json.JSONDecodeError) else -32600
                    print(json.dumps({"jsonrpc": "2.0", "id": request_id, "error": {"code": error_code, "message": str(exc)}}, ensure_ascii=True), flush=True)
        except KeyboardInterrupt:
            # SIGTERM is translated to KeyboardInterrupt so stdin processing
            # can stop cleanly without a traceback or non-JSON stdout output.
            pass
    finally:
        signal.signal(signal.SIGTERM, previous)
        runtime.close()

"""Command line interface for Specialist Runtime."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .registry import CAPABILITIES, get_spec
from .runtime import SpecialistRuntime
from .server import serve_http, serve_mcp
from .providers.ipc import WorkerError, run_worker
from .models import ModelArtifactError
from .environments import EnvironmentError


def _json_dump(value):
    print(json.dumps(value, ensure_ascii=True, indent=2))


def _human_result(value):
    if value.get("error"):
        error = value["error"]
        print(f"Error [{error.get('code')}]: {error.get('message')}", file=sys.stderr)
        return 1
    result = value.get("result") or {}
    print(f"{value['capability']}  provider={value['provider']}  model={value['model']}")
    if value["capability"] == "vision.ocr":
        blocks = result.get("blocks", [])
        print("\n".join(block.get("text", "") for block in blocks) or "No text detected.")
    elif value["capability"] == "vision.detect":
        items = result.get("items", [])
        print("\n".join(f"{item.get('label', 'object')} bbox={item.get('bbox')} confidence={item.get('confidence')}" for item in items) or "No objects detected.")
    elif value["capability"] == "audio.transcribe":
        print(result.get("text") or "No speech detected.")
    elif value["capability"] == "document.parse":
        print(result.get("markdown", ""))
    else:
        print(json.dumps(result, ensure_ascii=True, indent=2))
    performance = value.get("performance") or {}
    print(f"\nlatency={performance.get('latency_ms', 0)}ms cached={performance.get('cached', False)}")
    for warning in value.get("warnings", []):
        print(f"warning: {warning}", file=sys.stderr)
    return 0


def _human_doctor(value):
    system = value.get("system", {})
    print(f"Specialist Runtime {value.get('version', __version__)}")
    print("\nSystem")
    for key in ("os", "architecture", "cpu", "memory_gb", "metal", "mps", "ffmpeg", "onnxruntime"):
        if key in system:
            label = key.replace("_", " ").title()
            value_text = system[key]
            if isinstance(value_text, bool):
                value_text = "yes" if value_text else "no"
            print(f"{label:<16} {value_text}")
    print("\nCapabilities")
    for item in value.get("capabilities", []):
        marker = item.get("status", "unknown")
        print(f"{item['capability']:<22} {marker:<16} provider={item['provider']}")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="specialist", description="Local-first specialist capability runtime for any LLM")
    parser.add_argument("--version", action="version", version=f"specialist {__version__}")
    parser.add_argument("--home", help="Override the local runtime home (default: ~/.specialist)")
    parser.add_argument("--isolate", action="store_true", help="Run built-in providers in a separate worker process")
    parser.add_argument("--backend", choices=["auto", "real", "fallback"], default="auto", help="Provider selection policy")
    parser.add_argument("--with-dependencies", action="store_true", help="Create isolated provider environments and install optional packages")
    parser.add_argument("--allow-unverified-models", action="store_true", default=None, help="Allow optional providers to download weights without a SHA256 artifact")
    parser.add_argument("--max-loaded", type=int, default=4, help="Maximum simultaneously loaded providers")
    sub = parser.add_subparsers(dest="command", required=True)

    capabilities = sub.add_parser("capabilities", help="List the stable capability registry")
    capabilities.add_argument("--json", action="store_true", dest="as_json")
    doctor = sub.add_parser("doctor", help="Inspect system, dependencies and provider state")
    doctor.add_argument("--fix", action="store_true", help="Install safe local fallback markers")
    doctor.add_argument("--strict", action="store_true", help="Exit non-zero unless every capability is ready")
    doctor.add_argument("--json", action="store_true", dest="as_json")
    install = sub.add_parser("install", help="Install a capability, bundle or all")
    install.add_argument("target")
    install.add_argument("--source", help="Artifact URL (file:// and https:// are supported)")
    install.add_argument("--sha256", help="Expected SHA256 for --source")
    models = sub.add_parser("models", help="Manage model metadata and result cache")
    model_sub = models.add_subparsers(dest="models_command", required=True)
    model_sub.add_parser("list")
    remove = model_sub.add_parser("remove")
    remove.add_argument("target")
    pin = model_sub.add_parser("pin")
    pin.add_argument("target")
    unpin = model_sub.add_parser("unpin")
    unpin.add_argument("target")
    clean = model_sub.add_parser("clean")
    clean.add_argument("--max-age-hours", type=float)
    clean.add_argument("--max-entries", type=int)

    for command in ["detect", "segment", "ocr", "depth", "parse-screen", "parse-document", "transcribe", "vad"]:
        item = sub.add_parser(command)
        item.add_argument("input", help="Local input path")
        if command == "segment":
            item.add_argument("--prompt")
        item.add_argument("--json", action="store_true", dest="as_json")
        item.add_argument("--options", help="Additional options as a JSON object")

    serve = sub.add_parser("serve", help="Run local HTTP or MCP server")
    serve.add_argument("--mcp", action="store_true", help="Use MCP JSON-RPC over stdin/stdout")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8741)
    serve.add_argument("--token", help="Bearer token; required for non-loopback binds")
    serve.add_argument("--max-concurrency", type=int, default=4)
    serve.add_argument("--max-request-bytes", type=int, default=1024 * 1024)
    worker = sub.add_parser("_worker", help=argparse.SUPPRESS)
    worker.add_argument("--capability", required=True)
    worker.add_argument("--backend", choices=["auto", "real", "fallback"], default="fallback")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    runtime = SpecialistRuntime(home=args.home, isolate=args.isolate or args.command == "serve", backend=args.backend, with_dependencies=args.with_dependencies, max_loaded=args.max_loaded, allow_unverified_models=args.allow_unverified_models)
    if args.command == "capabilities":
        _json_dump(runtime.capabilities())
        return 0
    if args.command == "doctor":
        value = runtime.doctor(fix=args.fix)
        failed = any(item.get("status") != "ready" for item in value.get("capabilities", []))
        if args.as_json:
            _json_dump(value)
            return 1 if args.strict and failed else 0
        result = _human_doctor(value)
        return 1 if args.strict and failed else result
    if args.command == "install":
        try:
            _json_dump(runtime.install(args.target, source=args.source, sha256=args.sha256, with_dependencies=args.with_dependencies))
            return 0
        except (KeyError, WorkerError, ModelArtifactError, EnvironmentError, OSError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
    if args.command == "models":
        if args.models_command == "list":
            _json_dump(runtime.models())
        elif args.models_command == "remove":
            try:
                _json_dump(runtime.remove_model(args.target))
            except (KeyError, WorkerError, OSError) as exc:
                print(str(exc), file=sys.stderr)
                return 2
        elif args.models_command in {"pin", "unpin"}:
            try:
                _json_dump(runtime.pin_model(args.target, pinned=args.models_command == "pin"))
            except (KeyError, WorkerError, OSError) as exc:
                print(str(exc), file=sys.stderr)
                return 2
        else:
            age = args.max_age_hours * 3600 if args.max_age_hours is not None else None
            _json_dump(runtime.clean_cache(max_age_seconds=age, max_entries=args.max_entries))
        return 0
    if args.command == "serve":
        try:
            if args.mcp:
                serve_mcp(runtime, max_request_bytes=args.max_request_bytes)
            else:
                serve_http(runtime, args.host, args.port, token=args.token, max_concurrency=args.max_concurrency, max_request_bytes=args.max_request_bytes)
        except (OSError, ValueError) as exc:
            print(f"Could not start server: {exc}", file=sys.stderr)
            return 2
        return 0
    if args.command == "_worker":
        for line in sys.stdin:
            try:
                request = json.loads(line)
                request["capability"] = args.capability
                print(json.dumps(run_worker(request, backend=args.backend), ensure_ascii=True), flush=True)
            except Exception as exc:
                print(json.dumps({"error": {"code": "worker_protocol_error", "message": str(exc), "retryable": False}}, ensure_ascii=True), flush=True)
        return 0
    options = {}
    if args.options:
        try:
            options = json.loads(args.options)
            if not isinstance(options, dict):
                raise ValueError("options must be a JSON object")
        except ValueError as exc:
            print(f"Invalid --options: {exc}", file=sys.stderr)
            return 2
    if args.command == "segment" and args.prompt:
        options["prompt"] = args.prompt
    try:
        value = runtime.run(get_spec(args.command).name, args.input, options)
    except KeyError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.as_json:
        _json_dump(value)
        return 1 if value.get("error") else 0
    return _human_result(value)


if __name__ == "__main__":
    raise SystemExit(main())

"""Command line interface for Specialist Runtime."""

from __future__ import annotations

import argparse
import atexit
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
from .provider_manifest import ProviderCatalog, ProviderManifest, ProviderManifestError, builtin_manifests
from .node import ComputeNode, NodeError
from .hardware import detect_hardware


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

    provider = sub.add_parser("provider", help="Inspect and install provider manifests")
    provider_sub = provider.add_subparsers(dest="provider_command", required=True)
    provider_sub.add_parser("list", help="List built-in and installed provider manifests")
    validate = provider_sub.add_parser("validate", help="Validate a provider manifest without executing it")
    validate.add_argument("manifest")
    provider_install = provider_sub.add_parser("install", help="Install a local provider manifest into the catalog")
    provider_install.add_argument("manifest_or_name")

    explain = sub.add_parser("explain", help="Explain deterministic provider routing")
    explain.add_argument("capability")
    explain.add_argument("--options", help="Routing constraints as a JSON object")
    explain.add_argument("--json", action="store_true", dest="as_json")

    bench = sub.add_parser("bench", help="Measure a real provider on a local input")
    bench.add_argument("capability")
    bench.add_argument("input")
    bench.add_argument("--runs", type=int, default=3)
    bench.add_argument("--options")

    replay = sub.add_parser("replay", help="Read a previously cached result by its run identifier")
    replay.add_argument("run_id")

    pack = sub.add_parser("pack", help="List and install capability packs")
    pack_sub = pack.add_subparsers(dest="pack_command", required=True)
    pack_sub.add_parser("list")
    pack_install = pack_sub.add_parser("install")
    pack_install.add_argument("name")

    studio = sub.add_parser("studio", help="Print a Studio control-plane snapshot")
    studio_sub = studio.add_subparsers(dest="studio_command", required=True)
    studio_sub.add_parser("snapshot")

    node = sub.add_parser("node", help="Inspect Compute Fabric node metadata")
    node_sub = node.add_subparsers(dest="node_command", required=True)
    node_sub.add_parser("list")
    start = node_sub.add_parser("start", help="Run an authenticated node HTTP agent")
    start.add_argument("--host", default="127.0.0.1")
    start.add_argument("--port", type=int, default=8742)
    start.add_argument("--token", required=True)
    start.add_argument("--capabilities", default="all", help="Comma-separated capability names or all")
    register = node_sub.add_parser("register")
    register.add_argument("metadata", help="JSON file containing node metadata")

    for command in ["detect", "segment", "ocr", "depth", "parse-screen", "parse-document", "transcribe", "vad"]:
        item = sub.add_parser(command)
        item.add_argument("input", help="Local input path")
        if command == "segment":
            item.add_argument("--prompt")
        item.add_argument("--profile", choices=["fast", "balanced", "quality", "ultra"])
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
    # Ensure persistent worker threads are joined before interpreter teardown,
    # including command paths that return early after printing JSON.
    atexit.register(runtime.close)
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
    if args.command == "provider":
        catalog = ProviderCatalog(runtime.cache.home / "providers")
        try:
            if args.provider_command == "list":
                values = [item.to_dict() for item in builtin_manifests()]
                values.extend(item.to_dict() for item in catalog.list())
                _json_dump(values)
            elif args.provider_command == "validate":
                _json_dump(ProviderManifest.load(args.manifest).to_dict())
            else:
                target = Path(args.manifest_or_name).expanduser()
                manifest = catalog.install_path(target) if target.exists() else catalog.get(args.manifest_or_name)
                if manifest is None:
                    raise ProviderManifestError("provider install expects a local manifest path; remote marketplace installation is not enabled")
                _json_dump(manifest.to_dict())
            return 0
        except (ProviderManifestError, OSError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
    if args.command == "explain":
        options = {}
        if args.options:
            try:
                options = json.loads(args.options)
                if not isinstance(options, dict):
                    raise ValueError("options must be a JSON object")
            except ValueError as exc:
                print(f"Invalid --options: {exc}", file=sys.stderr)
                return 2
        try:
            _json_dump(runtime.explain(args.capability, options))
            return 0
        except (KeyError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
    if args.command == "bench":
        options = {}
        if args.options:
            try:
                options = json.loads(args.options)
                if not isinstance(options, dict):
                    raise ValueError("options must be a JSON object")
            except ValueError as exc:
                print(f"Invalid --options: {exc}", file=sys.stderr)
                return 2
        try:
            _json_dump(runtime.benchmark(args.capability, args.input, runs=args.runs, options=options))
            return 0
        except (KeyError, ValueError, OSError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
    if args.command == "replay":
        try:
            _json_dump(runtime.replay(args.run_id))
            return 0
        except (KeyError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
    if args.command == "pack":
        try:
            _json_dump(runtime.packs() if args.pack_command == "list" else runtime.install_pack(args.name, with_dependencies=args.with_dependencies))
            return 0
        except (KeyError, ValueError, OSError, WorkerError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
    if args.command == "studio":
        try:
            from .studio import snapshot

            _json_dump(snapshot(runtime))
            return 0
        except (ValueError, OSError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
    if args.command == "node":
        try:
            if args.node_command == "list":
                _json_dump([item.to_dict() for item in runtime.nodes.list()])
            elif args.node_command == "start":
                capabilities = list(CAPABILITIES) if args.capabilities == "all" else [get_spec(item.strip()).name for item in args.capabilities.split(",") if item.strip()]
                node = ComputeNode.create("specialist-node", capabilities=tuple(capabilities), metadata={"endpoint": f"http://{args.host}:{args.port}", "token_env": "SPECIALIST_API_TOKEN"}, local=args.host in {"127.0.0.1", "localhost", "::1"})
                runtime.nodes.register(node)
                serve_http(runtime, args.host, args.port, token=args.token, max_request_bytes=64 * 1024 * 1024)
            else:
                path = Path(args.metadata).expanduser()
                if path.is_symlink() or not path.is_file():
                    raise NodeError("node metadata must be a regular file")
                node = ComputeNode.from_dict(json.loads(path.read_text(encoding="utf-8")))
                _json_dump(runtime.nodes.register(node).to_dict())
            return 0
        except (NodeError, OSError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
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
    if getattr(args, "profile", None):
        options["profile"] = args.profile
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

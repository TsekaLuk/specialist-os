# Engineering integration

Codex MCP configuration uses the installed executable:

```toml
[mcp_servers.specialist_os]
command = "specialist"
args = ["--backend", "real", "--isolate", "--max-loaded", "2", "serve", "--mcp"]
```

Prepare requested capabilities once through the CLI. MCP keeps the runtime alive
across tool calls. For a Python service, own one runtime and close it at shutdown:

```python
from specialist.runtime import SpecialistRuntime

runtime = SpecialistRuntime(backend="real", isolate=True, max_loaded=2)
try:
    result = runtime.run("vision.ocr", "/absolute/invoice.png")
    for artifact in result.get("artifacts", []):
        path = runtime.artifacts.resolve(artifact["uri"])
finally:
    runtime.close()
```

The HTTP server defaults to loopback. Prefer MCP for a local agent. Authentication
and deployment details live in the repository's `docs/deployment.md`.

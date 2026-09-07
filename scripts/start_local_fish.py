"""Start an explicitly prepared Fish S2 checkout on an unused loopback port."""

import argparse
import json
from pathlib import Path
import socket
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--port", type=int, default=18080)
    args = parser.parse_args()
    source = args.source.resolve()
    python = source / ".venv/bin/python"
    checkpoint = source / "checkpoints/s2-pro"
    for path in (python, source / "tools/api_server.py", checkpoint / "codec.pth", checkpoint / "model-00001-of-00002.safetensors", checkpoint / "model-00002-of-00002.safetensors"):
        if not path.is_file():
            raise FileNotFoundError(path)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", args.port))
    command = [str(python), "tools/api_server.py", "--listen", f"127.0.0.1:{args.port}", "--device", "mps", "--llama-checkpoint-path", str(checkpoint), "--decoder-checkpoint-path", str(checkpoint / "codec.pth")]
    log_path = source.parent / "fish-s2-server.log"
    with log_path.open("ab") as log:
        process = subprocess.Popen(command, cwd=source, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    state = {"pid": process.pid, "endpoint": f"http://127.0.0.1:{args.port}", "log": str(log_path), "command": command}
    (source.parent / "fish-s2-server.json").write_text(json.dumps(state, indent=2))
    print(json.dumps(state, indent=2))


if __name__ == "__main__":
    main()

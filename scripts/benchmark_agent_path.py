"""Measure fresh CLI versus reusable batches using real providers."""

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/demo"


def call(arguments):
    started = time.perf_counter()
    result = subprocess.run([sys.executable, "-m", "specialist", *arguments], cwd=ROOT, capture_output=True, text=True, timeout=240)
    if result.returncode:
        raise RuntimeError(result.stderr or result.stdout)
    return json.loads(result.stdout), round((time.perf_counter() - started) * 1000, 2), len(result.stdout.encode())


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    _, full_ms, full_bytes = call(["capabilities"])
    _, compact_ms, compact_bytes = call(["capabilities", "--compact"])
    _, detail_ms, detail_bytes = call(["capabilities", "vision.detect"])
    source = str(ROOT / "docs/assets/e2e/bus-input.jpg")
    options = {"no_cache": True, "device": "cpu"}
    fresh = []
    for index in range(3):
        value, elapsed, _ = call(["--backend", "real", "--isolate", "detect", source, "--json", "--options", json.dumps(options)])
        (OUT / f"fresh-{index}.json").write_text(json.dumps(value, indent=2))
        fresh.append(elapsed)
    requests = [{"capability": "vision.detect", "input": source, "options": options}] * 3
    path = OUT / "batch.json"
    path.write_text(json.dumps(requests, indent=2))
    batch, batch_ms, _ = call(["--backend", "real", "--isolate", "batch", str(path)])
    (OUT / "batch-results.json").write_text(json.dumps(batch, indent=2))
    if any(item.get("error") or item["performance"]["cached"] for item in batch["results"]):
        raise RuntimeError("benchmark requires successful uncached results")
    report = {"python": sys.version, "discovery": {"full": {"ms": full_ms, "bytes": full_bytes}, "compact": {"ms": compact_ms, "bytes": compact_bytes}, "selected": {"ms": detail_ms, "bytes": detail_bytes}}, "fresh_cli_ms": fresh, "batch_wall_ms": batch_ms, "batch_inference": [item["performance"] for item in batch["results"]], "speedup": round(sum(fresh) / batch_ms, 2), "scope": "Three CPU YOLO calls, weights already downloaded, result cache disabled"}
    (OUT / "performance.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

"""Execute selected live-demo stages through the real CLI and retain evidence."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs/assets/e2e"
STAGES = {
    "vision": [
        ("media.probe", "video-input.mp4", {}),
        ("vision.detect", "bus-input.jpg", {"device": "cpu"}),
        ("vision.segment", "bus-input.jpg", {"bbox": [14.35, 226.99, 800.55, 739.18]}),
        ("vision.depth", "bus-input.jpg", {}),
        ("vision.ocr", "ocr-table.png", {}),
    ],
    "audio": [
        ("audio.vad", "meeting-two-speaker.wav", {}),
        ("audio.transcribe", "meeting-two-speaker.wav", {}),
        ("speech.diarize", "meeting-two-speaker.wav", {"min_speakers": 2, "max_speakers": 2, "exclusive": True}),
        ("audio.denoise", "meeting-two-speaker-noisy.wav", {"strength": "balanced"}),
    ],
    "documents": [
        ("screen.parse", "specialist-github-screen.png", {"max_elements": 200, "caption_batch_size": 16, "min_confidence": 0.5}),
        ("document.parse", "brief-input.pdf", {}),
    ],
}
STAGES["screen"] = [STAGES["documents"][0]]
STAGES["document"] = [STAGES["documents"][1]]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=STAGES)
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--screen-device", choices=("cpu", "mps", "cuda"), default="cpu")
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    output = ROOT / "output/demo/rehearsals" / stamp
    output.mkdir(parents=True)
    requests = [
        {"capability": name, "input": str(ASSETS / source), "options": {**options, **({"device": args.screen_device} if name == "screen.parse" else {}), "no_cache": True}}
        for name, source, options in STAGES[args.stage]
    ]
    request_path = output / "requests.json"
    request_path.write_text(json.dumps(requests, indent=2), encoding="utf-8")
    command = [sys.executable, "-m", "specialist", "--backend", "real", "--isolate", "batch", str(request_path), "--keep-going"]
    started = time.perf_counter()
    process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=os.name == "posix")
    try:
        stdout, stderr = process.communicate(timeout=args.timeout)
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        stdout, stderr = process.communicate()
    (output / "stdout.json").write_text(stdout, encoding="utf-8")
    (output / "stderr.log").write_text(stderr, encoding="utf-8")
    try:
        results = json.loads(stdout)["results"]
    except (ValueError, KeyError, TypeError):
        print(f"CLI did not return a batch result; inspect {output}", file=sys.stderr)
        return 1
    summary = {
        "stage": args.stage,
        "created_at": stamp,
        "wall_seconds": round(time.perf_counter() - started, 3),
        "evidence": str(output),
        "results": [
            {"capability": item["capability"], "provider": item.get("provider"),
             "performance": item.get("performance"), "error": item.get("error"),
             "status": (item.get("result") or {}).get("status")}
            for item in results
        ],
    }
    summary["passed"] = process.returncode == 0 and len(results) == len(requests) and all(
        not item.get("error") and item.get("performance", {}).get("cached") is False
        and (item.get("result") or {}).get("status") != "degraded"
        for item in results
    )
    (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

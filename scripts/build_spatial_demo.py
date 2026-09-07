"""Package verified experimental and photographed-calibration results for viewing."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generation", type=Path, required=True)
    parser.add_argument("--scene", type=Path, required=True)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--node-modules", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    records = []
    for key, source, title in (("generation", args.generation, "图片生成 3D"), ("scene", args.scene, "场景几何")):
        result = json.loads((source / "result.json").read_text())
        if result.get("error") or result.get("performance", {}).get("cached") is not False:
            raise ValueError(f"No successful uncached evidence for {key}")
        target = output / key
        target.mkdir(exist_ok=True)
        for artifact in result["artifacts"]:
            path = source / artifact["file"]
            if hashlib.sha256(path.read_bytes()).hexdigest() != artifact["sha256"]:
                raise ValueError(f"Artifact checksum mismatch: {path}")
            shutil.copyfile(path, target / path.name)
        shutil.copyfile(source / "result.json", target / "result.json")
        records.append({"id": key, "title": title, "mesh": f"{key}/mesh.glb", "image": f"{key}/prepared.png", "evidence": f"{key}/result.json", "provider": result["provider"], "result": result["result"], "performance": result["performance"]})
    target = output / "calibration"
    target.mkdir(exist_ok=True)
    summary = json.loads((args.calibration / "summary.json").read_text())
    calibration = json.loads((args.calibration / "vision.geometry.calibrate_camera.json").read_text())
    pose = json.loads((args.calibration / "vision.geometry.solve_pnp.json").read_text())
    if calibration.get("error") or pose.get("error") or calibration["result"].get("method") != "opencv.calibrateCamera":
        raise ValueError("Photographed calibration evidence is required")
    for filename in ("summary.json", "pose-overlay.png", "inputs.json", "vision.geometry.calibrate_camera.json", "vision.geometry.solve_pnp.json"):
        shutil.copyfile(args.calibration / filename, target / filename)
    records.append({"id": "calibration", "title": "相机标定与位姿", "image": "calibration/pose-overlay.png", "evidence": "calibration/vision.geometry.solve_pnp.json", "provider": "OpenCV", "result": {**summary, "camera_matrix": calibration["result"]["camera_matrix"], "image_size": calibration["result"]["image_size"]}, "performance": pose["performance"]})
    (output / "data.json").write_text(json.dumps(records, ensure_ascii=False, indent=2))
    shutil.copyfile(ROOT / "scripts/demo_spatial.html", output / "index.html")
    shutil.copyfile(ROOT / "docs/assets/brand/specialist-os-logo-b-transparent.png", output / "logo.png")
    vendor = output / "vendor"
    vendor.mkdir(exist_ok=True)
    shutil.copytree(args.node_modules / "three", vendor / "three", dirs_exist_ok=True)
    shutil.copyfile(args.node_modules / "lucide/dist/umd/lucide.js", vendor / "lucide.js")
    print(output / "index.html")


if __name__ == "__main__":
    main()

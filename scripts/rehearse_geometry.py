"""Calibrate and solve pose through the CLI using real OpenCV chessboard photos."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import urllib.error
import urllib.request

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
REVISION = "415ba6a444e341dc98b7fa8a35592c9f24a4de01"


def prepare_inputs(output):
    """Download pinned photographs and detect the shared calibration inputs."""
    output.mkdir(parents=True, exist_ok=True)
    board = np.zeros((54, 3), dtype=np.float32)
    board[:, :2] = np.mgrid[0:9, 0:6].T.reshape(-1, 2)
    objects, images, sources = [], [], []
    image_size = None
    for index in range(1, 15):
        name = f"left{index:02d}.jpg"
        url = f"https://raw.githubusercontent.com/opencv/opencv/{REVISION}/samples/data/{name}"
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                data = response.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                continue
            raise
        path = output / name
        path.write_bytes(data)
        gray = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)
        found, corners = cv2.findChessboardCornersSB(gray, (9, 6))
        sources.append({"file": name, "url": url, "sha256": hashlib.sha256(data).hexdigest(), "corners_found": bool(found)})
        if found:
            objects.append(board.tolist())
            images.append(corners.reshape(-1, 2).tolist())
            image_size = [gray.shape[1], gray.shape[0]]
    if len(objects) < 3:
        raise RuntimeError("Fewer than three photographed chessboards were detected")
    (output / "inputs.json").write_text(json.dumps({"sources": sources, "square_unit": "one board square; physical size unspecified"}, indent=2))
    input_path = output / next(source["file"] for source in sources if source["corners_found"])
    return input_path, {"image_size": image_size, "object_points": objects, "image_points": images}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--python", default=sys.executable)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    input_path, calibration_options = prepare_inputs(output)
    objects, images = calibration_options["object_points"], calibration_options["image_points"]

    def run(capability, options):
        request = [{"capability": capability, "input": str(input_path), "options": {**options, "no_cache": True}}]
        request_file = output / f"{capability}.request.json"
        request_file.write_text(json.dumps(request))
        command = [args.python, "-m", "specialist", "--backend", "real", "--isolate", "batch", str(request_file)]
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=180)
        (output / f"{capability}.stderr.log").write_text(completed.stderr)
        envelope = json.loads(completed.stdout)["results"][0]
        (output / f"{capability}.json").write_text(json.dumps(envelope, indent=2))
        if completed.returncode or envelope.get("error") or envelope["performance"]["cached"]:
            raise RuntimeError(f"CLI failed: {envelope.get('error')}")
        return envelope

    calibration = run("vision.geometry.calibrate_camera", calibration_options)
    camera = calibration["result"]["camera_matrix"]
    distortion = calibration["result"]["distortion"]
    pose = run("vision.geometry.solve_pnp", {"object_points": objects[0], "image_points": images[0], "camera_matrix": camera, "distortion": distortion})
    photograph = cv2.imread(pose["input"]["path"])
    result = pose["result"]
    cv2.drawChessboardCorners(photograph, (9, 6), np.array(images[0], np.float32).reshape(-1, 1, 2), True)
    cv2.drawFrameAxes(photograph, np.array(camera), np.array(distortion), np.array(result["rotation_vector"]), np.array(result["translation_vector"]), 3)
    cv2.imwrite(str(output / "pose-overlay.png"), photograph)
    summary = {"views": len(objects), "calibration_rms_px": calibration["result"]["reprojection_error"], "pnp_rms_px": result["reprojection_error"], "pose": result, "object_points": objects[0], "input_image": Path(pose["input"]["path"]).name}
    (output / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps({key: value for key, value in summary.items() if key not in {"pose", "object_points"}}, indent=2))


if __name__ == "__main__":
    main()

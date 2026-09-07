"""Local image-to-asset and scene-geometry evaluations using pinned models."""

from contextlib import redirect_stdout
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

from ..artifacts import ArtifactStore


MODELS = {
    "generate-3d": {
        "provider": "triposr",
        "semantic_type": "generative_3d",
        "model": "stabilityai/TripoSR",
        "revision": "5b521936b01fbe1890f6f9baed0254ab6351c04a",
        "file": "model.ckpt",
        "sha256": "429e2c6b22a0923967459de24d67f05962b235f79cde6b032aa7ed2ffcd970ee",
        "source_revision": "107cefdc244c39106fa830359024f6a2f1c78871",
    },
    "scene-geometry": {
        "provider": "moge2",
        "semantic_type": "estimated_scene_geometry",
        "model": "Ruicheng/moge-2-vitb-normal",
        "revision": "ca5f0e07ff01d3e5a364c1d954ed12ee1814b368",
        "file": "model.pt",
        "sha256": "16b8110e86d5dc5a849db120ca96ef3a223fd30b0c9146d1d81db504073da5f6",
        "source_revision": "b942f00bdc2a2a23ebb474fbe034d487e6dcceec",
    },
}


def digest(path):
    checksum = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def _generate(args, image, output):
    import numpy as np
    import torch
    from PIL import Image
    from tsr.system import TSR

    model = TSR.from_pretrained(str(args.checkpoint), "config.yaml", "model.ckpt").eval().to(args.device)
    model.renderer.set_chunk_size(4096)
    rgba = np.asarray(image.convert("RGBA"), dtype=np.float32) / 255
    prepared = Image.fromarray(np.uint8((rgba[..., :3] * rgba[..., 3:] + 0.5 * (1 - rgba[..., 3:])) * 255))
    prepared.save(output / "prepared.png")
    with torch.inference_mode():
        codes = model([prepared], device=args.device)
        model.set_marching_cubes_resolution(args.resolution)
        # The compiled marching-cubes kernel runs on CPU; model inference keeps
        # its explicitly selected device. Record this split in the result.
        native_mc = model.isosurface_helper.mc_func
        model.isosurface_helper.mc_func = lambda field, level: native_mc(field.cpu(), level)
        mesh = model.extract_mesh(codes, True, resolution=args.resolution)[0]
    if len(mesh.vertices) == 0 or len(mesh.faces) == 0 or not np.isfinite(mesh.vertices).all():
        raise ValueError("TripoSR returned an empty or non-finite mesh")
    mesh.export(output / "mesh.glb")
    mesh.export(output / "mesh.ply")
    return {
        "vertices": len(mesh.vertices), "faces": len(mesh.faces),
        "scale": "arbitrary_object_space", "metric_ground_truth": False,
        "mesh_coordinates": "TripoSR object space, Z up; viewer rotates X by -pi/2",
        "mesh_extraction_device": "cpu", "resolution": args.resolution,
        "files": ["mesh.glb", "mesh.ply", "prepared.png"],
    }


def _scene(args, image, output):
    import numpy as np
    import torch
    import trimesh
    import utils3d
    from PIL import Image
    from moge.model.v2 import MoGeModel

    image.thumbnail((640, 640))
    rgb = np.asarray(image.convert("RGB"))
    weights = torch.load(args.checkpoint / "model.pt", map_location="cpu", weights_only=True)
    model = MoGeModel(**weights["model_config"])
    model.load_state_dict(weights["model"], strict=True)
    model = model.eval().to(args.device)
    tensor = torch.tensor(rgb / 255, dtype=torch.float32, device=args.device).permute(2, 0, 1)
    with torch.inference_mode():
        prediction = model.infer(tensor, resolution_level=2, use_fp16=False)
    arrays = {key: value.detach().cpu().numpy() for key, value in prediction.items()}
    np.savez_compressed(output / "geometry.npz", **arrays)
    points, depth = arrays["points"], arrays["depth"]
    valid = arrays["mask"] & np.isfinite(points).all(axis=-1)
    clean = valid & ~utils3d.np.depth_map_edge(depth, rtol=0.03)
    faces, vertices, colors = utils3d.np.build_mesh_from_map(points, rgb.astype(np.float32) / 255, mask=clean, tri=True)
    if len(vertices) == 0 or len(faces) == 0 or not np.isfinite(vertices).all():
        raise ValueError("MoGe returned no finite scene surface")
    vertices = vertices * [1, -1, -1]
    trimesh.Trimesh(vertices=vertices, faces=faces, vertex_colors=colors, process=False).export(output / "mesh.glb")
    trimesh.points.PointCloud(vertices, colors=colors).export(output / "pointcloud.ply")
    if "normal" in arrays:
        normal = np.uint8(np.clip(arrays["normal"] * 0.5 + 0.5, 0, 1) * 255)
        normal[~valid] = 0
        Image.fromarray(normal).save(output / "normal.png")
    image.save(output / "prepared.png")
    files = ["mesh.glb", "pointcloud.ply", "geometry.npz", "prepared.png"]
    if "normal" in arrays:
        files.append("normal.png")
    return {
        "vertices": len(vertices), "faces": len(faces),
        "intrinsics_normalized": arrays["intrinsics"].tolist(),
        "scale": "model_estimated_meters", "metric_ground_truth": False,
        "mesh_coordinates": "OpenGL: x right, y up, z backward",
        "array_coordinates": "OpenCV: x right, y down, z forward",
        "files": files,
    }


def execute(args):
    model = MODELS[args.experiment]
    envelope = {
        "capability": "experimental." + args.experiment.replace("-", "_"),
        "provider": model["provider"], "model": model["model"],
        "core": False, "result": None, "artifacts": [], "warnings": [], "error": None,
        "provenance": {**model, "command": [sys.executable, "-m", "specialist", *sys.argv[1:]], "created_at": datetime.now(timezone.utc).isoformat()},
    }
    started = time.perf_counter()
    output = None
    try:
        if not 32 <= args.resolution <= 256:
            raise ValueError("resolution must be between 32 and 256")
        source, checkpoint, input_path = Path(args.source).resolve(), Path(args.checkpoint).resolve(), Path(args.input).resolve()
        if not source.is_dir() or not input_path.is_file():
            raise ValueError("source directory and input file must exist")
        if digest(checkpoint / model["file"]) != model["sha256"]:
            raise ValueError("checkpoint SHA256 does not match the pinned model")
        destination = Path(args.output_dir).resolve()
        destination.mkdir(parents=True, exist_ok=False)
        output = destination
        args.checkpoint = checkpoint
        envelope["input"] = {"path": str(input_path), "sha256": digest(input_path)}
        envelope["provenance"]["source_path"] = str(source)
        envelope["provenance"]["source_files_sha256"] = {
            path.relative_to(source).as_posix(): digest(path)
            for path in sorted((source / ("tsr" if args.experiment == "generate-3d" else "moge")).rglob("*.py"))
        }
        sys.path.insert(0, str(source))
        with redirect_stdout(sys.stderr):
            import torch
            from PIL import Image

            if args.device == "mps" and not torch.backends.mps.is_available():
                raise ValueError("MPS is unavailable")
            if args.device == "cuda" and not torch.cuda.is_available():
                raise ValueError("CUDA is unavailable")
            with Image.open(input_path) as opened:
                image = opened.copy()
            inference_started = time.perf_counter()
            payload = (_generate if args.experiment == "generate-3d" else _scene)(args, image, output)
            if args.device == "mps":
                torch.mps.synchronize()
            elif args.device == "cuda":
                torch.cuda.synchronize()
            inference_ms = round((time.perf_counter() - inference_started) * 1000, 2)
        store = ArtifactStore(Path(args.home or Path.home() / ".specialist") / "artifacts")
        for filename in payload.pop("files"):
            mime = {".glb": "model/gltf-binary", ".ply": "application/ply", ".png": "image/png", ".npz": "application/x-numpy-npz"}[Path(filename).suffix]
            artifact = store.put_file(output / filename, mime=mime, metadata={"semantic_type": model["semantic_type"], "source_name": filename}).to_dict()
            artifact["file"] = filename
            envelope["artifacts"].append(artifact)
        envelope["result"] = {"semantic_type": model["semantic_type"], **payload}
        envelope["performance"] = {"device": args.device, "cached": False, "inference_ms": inference_ms}
    except Exception as exc:
        envelope["error"] = {"code": "experimental_provider_failed", "message": str(exc), "type": type(exc).__name__}
    envelope.setdefault("performance", {})["wall_ms"] = round((time.perf_counter() - started) * 1000, 2)
    try:
        import resource

        envelope["performance"]["process_peak_rss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024)
    except ImportError:
        envelope["performance"]["process_peak_rss_bytes"] = None
    if output is not None and output.is_dir():
        (output / "result.json").write_text(json.dumps(envelope, indent=2), encoding="utf-8")
    return envelope

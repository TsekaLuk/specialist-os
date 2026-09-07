# Local spatial evaluation

The two experimental CLI routes stay outside Core 15. They require an explicitly
prepared environment and trusted upstream checkout. They do not participate in
`install core`. Standard Core users download only the models needed by their task.

## Reproduce on the prepared Mac

Run from the repository root. Output directories must be new.

```bash
output/demo/runtime/spatial-env/bin/python -m specialist experimental generate-3d \
  output/demo/runtime/TripoSR-107cefdc244c39106fa830359024f6a2f1c78871/examples/chair.png \
  --source output/demo/runtime/TripoSR-107cefdc244c39106fa830359024f6a2f1c78871 \
  --checkpoint output/demo/runtime/triposr-weights \
  --output-dir output/demo/spatial/triposr-new --device mps --resolution 128

output/demo/runtime/spatial-env/bin/python -m specialist experimental scene-geometry \
  docs/assets/e2e/bus-input.jpg \
  --source output/demo/runtime/MoGe-b942f00bdc2a2a23ebb474fbe034d487e6dcceec \
  --checkpoint output/demo/runtime/moge2-weights \
  --output-dir output/demo/spatial/moge2-new --device mps

output/demo/runtime/spatial-env/bin/python scripts/rehearse_geometry.py \
  --output output/demo/spatial/chessboard-new --python .venv/bin/python
```

The chair file is an upstream input image. Specialist OS locally generated the
GLB/PLY outputs. The bus photo generates a visible-surface estimate from one image.
Each result JSON records provenance, semantic type, artifact SHA256 and timing.
Raw MoGe arrays use OpenCV axes; exported mesh uses OpenGL axes. TripoSR's mesh
uses Z-up object coordinates, rotated for display by the viewer.

## Environment baseline

Python 3.12, torch 2.8.0, torchvision 0.23.0, transformers 4.35.0,
numpy 1.26.4, OpenCV 4.10.0.84, trimesh 4.12.2, omegaconf 2.3.0,
einops 0.7.0, rembg 2.0.69. `torchmcubes` was built from
`3381600ddc3d2e4d74222f8495866be5fafbace4` with CMake and a C++ compiler.
`utils3d` uses commit `3fab839f0be9931dac7c8488eb0e1600c236e183`.
Source and model revisions are listed in [the evaluation record](spatial-watchlist.md).
TripoSR also resolves the DINO configuration through Hugging Face on first load.
The current environment is an evaluation setup, not yet a portable installer.

## Viewer

```bash
python scripts/build_spatial_demo.py \
  --generation output/demo/spatial/triposr-chair-01 \
  --scene output/demo/spatial/moge2-bus-03 \
  --calibration output/demo/spatial/chessboard-01 \
  --output output/demo/spatial-viewer/site \
  --node-modules output/demo/spatial-viewer/node_modules
python -m http.server 8742 --bind 127.0.0.1 --directory output/demo
```

Viewer dependencies: `three@0.180.0`, `lucide@0.468.0`. Install them in
`output/demo/spatial-viewer` when preparing another machine. Open
`http://127.0.0.1:8742/spatial-viewer/site/`.
`scripts/check_spatial_demo.cjs` uses Playwright to check all three cases on
desktop and mobile, including nonblank canvas pixels, rotation, zoom and wireframe.

## Camera calibration contract

`vision.geometry.calibrate_camera` now performs OpenCV multi-view calibration.
Provide at least three sets of matching `object_points[view][point][xyz]` and
`image_points[view][point][xy]`, at least six points per view, plus `image_size`.
The old single-view heuristic input is rejected. Results retain camera matrix,
distortion and image size, adding method, view count, poses and RMS residual.
Use the returned matrix and distortion with `vision.geometry.solve_pnp`.

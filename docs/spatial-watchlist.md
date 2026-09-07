# Spatial watchlist

Owner: Specialist OS maintainers. Established: 2026-09-07 under
[ADR-003](adr/003-defer-spatial-3d-core.md). Status: watchlist, outside Core.

This is an evaluation backlog. MoGe 2 and TripoSR have local CLI evaluation
records below, without a Core admission decision. Reassess at provider releases or
when concrete integrations supply evidence, not on benchmark rank alone.

| Candidate | Evaluation scope | Evidence status |
| --- | --- | --- |
| MoGe family | Monocular geometry and scale semantics | MoGe 2 evaluated locally on MPS |
| TripoSR | Single-image asset generation | Evaluated locally on MPS, optional track |
| VGGT family | Multi-view geometry and camera outputs | Pending evaluation |
| Geometry foundation models | Stable shared geometry abstraction | Pending ecosystem review |
| Local multi-view reconstruction | Reconstruction from multiple images | Pending provider selection |
| Local metric geometry | Calibrated scale and measurable outputs | Pending provider selection |
| Local camera-pose models | Intrinsics, pose conventions and uncertainty | Pending provider selection |
| COLMAP / GLOMAP | SfM and reconstruction pipelines | Pending evaluation |
| Open3D | Point clouds, registration and geometry operators | Pending evaluation |
| RTAB-Map | Mapping and localization infrastructure | Pending evaluation |
| GTSAM | Geometry optimization and sensor fusion | Pending evaluation |
| AprilTag | Fiducial detection and pose estimation | Pending evaluation |

## Evidence record

Create one version-specific record per candidate using these fields. All fields
remain **unassessed** unless recorded below. Unknown is different from
unsupported. Claims require dated upstream links or local run artifacts.

| Field | Required evidence |
| --- | --- |
| Capabilities | Exact tasks and supported input modalities |
| Version and parameter count | Release/commit, checkpoint and count, or not applicable for a library |
| Mac support | OS, architecture, installation command and result |
| MPS support | Actual execution device and unsupported operators |
| ONNX / CoreML | Export/runtime availability and tested version |
| VRAM / RAM | Peak use, resolution, frame count, hardware and measurement method |
| License | Code and each weight license, commercial restrictions |
| Maintenance activity | Dated releases, fixes and maintainer activity |
| Downstream adoption | Named integrations with public evidence and deployment context |
| Inference latency | Cold/warm timing, preparation separated, command and input hashes |
| Output semantics | Relative/metric scale, units, coordinates, intrinsics, poses and uncertainty |
| Deployment path | Packaging, model provenance, checksum and cross-platform evidence |
| Evaluation artifacts | CLI logs, original inputs and resulting artifacts |
| Decision | Remain watchlist, experiment, optional pack, or new Core ADR proposal |

## Promotion gate

Promotion requires a stable generic API, practical laptop execution without a
mandatory 24 GB NVIDIA GPU, production adoption, measurable structured outputs
and a recognizable default provider ecosystem. A Core proposal must satisfy all
five requirements in ADR-003 section 17 and its reopening conditions.

Experiments remain under `experimental/` or `packs/spatial-experimental/` with
`experimental.spatial.*` names. They cannot modify Core contracts or installs.

Hunyuan3D, TRELLIS, Tripo and Meshy belong to the separate optional heavy track.
Generated asset quality is not evidence for Spatial Core admission.

## Local evaluation, 2026-09-07

Apple M4 Pro, 48 GB unified memory. Prepared weights and dependencies, no result
cache. These are single-input functional measurements, not quality benchmarks.

| Route | Pinned source | Pinned model revision | Local outcome |
| --- | --- | --- | --- |
| TripoSR | `107cefdc244c39106fa830359024f6a2f1c78871` | `stabilityai/TripoSR@5b521936b01fbe1890f6f9baed0254ab6351c04a` | 38.091 s, 10,019 vertices, 19,948 faces |
| MoGe 2 | `b942f00bdc2a2a23ebb474fbe034d487e6dcceec` | `Ruicheng/moge-2-vitb-normal@ca5f0e07ff01d3e5a364c1d954ed12ee1814b368` | 3.552 s, 290,007 vertices, 568,186 faces |

TripoSR runs model inference on MPS and surface extraction on CPU at resolution
128. Its generated chair uses arbitrary object scale. MoGe 2 runs on MPS at
resolution level 2 with a 640-pixel maximum input dimension. Its single-image
surface uses model-estimated meters, with unknown regions and depth-edge holes.
It does not constitute multi-view reconstruction or a measured scene survey.
MoGe's process peak RSS was approximately 1.3 GB; this is not GPU-only memory.

Results: `output/demo/spatial/triposr-chair-01/result.json` and
`output/demo/spatial/moge2-bus-03/result.json`. Each records command, input hash,
checkpoint hash, actual source file hashes, device, timings and artifact hashes.
Source revision identifies the intended upstream version; the source tree is
operator-supplied. ONNX, CoreML, Windows, Linux, multi-view quality and commercial
deployment remain unassessed. Reproduction: [spatial evaluation](spatial-evaluation.md).

Existing OpenCV operators also ran on 11 photographed chessboards through CLI
batch: calibration RMS 0.248463 px, first-view PnP RMS 0.192829 px. Coordinates
are board-square units. These are in-sample reprojection residuals, not held-out
accuracy or physical measurement validation. Evidence: `output/demo/spatial/chessboard-01`.

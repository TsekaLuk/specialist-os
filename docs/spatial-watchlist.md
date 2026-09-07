# Spatial watchlist

Owner: Specialist OS maintainers. Established: 2026-09-07 under
[ADR-003](adr/003-defer-spatial-3d-core.md). Status: watchlist, outside Core.

This is an evaluation backlog. No candidate below has a Specialist OS local
benchmark or admission decision recorded yet. Reassess at provider releases or
when concrete integrations supply evidence, not on benchmark rank alone.

| Candidate | Evaluation scope | Evidence status |
| --- | --- | --- |
| MoGe family | Monocular geometry and scale semantics | Pending evaluation |
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
are currently **unassessed** for each candidate above. Unknown is different from
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

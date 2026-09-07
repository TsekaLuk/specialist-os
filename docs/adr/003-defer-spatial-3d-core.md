# ADR-003 — Defer Spatial / 3D Core Expansion

**Status:** Accepted
**Decision Type:** Architecture / Product Scope
**Supersedes:** Previous proposal to make Spatial / 3D Intelligence the next Core expansion
**Applies To:** Specialist OS
**Core Capability Baseline:** Core 15
**Date:** 2026-09-07

---

# 1. Decision Summary

Specialist OS SHALL NOT introduce a Spatial / 3D Intelligence domain into the Core Capability Set at the current stage.

The Core Capability Set SHALL remain frozen at the current 15 production capabilities.

3D-related technologies SHALL instead be separated into two non-Core tracks:

```text
Spatial / Geometry
→ Watchlist / Experimental Providers

Generative 3D
→ Optional Heavy Generative Pack
```

The previous architectural direction:

```text
Core 15
↓
Spatial / World Pack
↓
3D World Representation
```

is therefore deferred.

The new direction is:

```text
Core 15
├── Stable Core
│
├── Optional Specialist Packs
│
├── Heavy Generative Packs
│     └── Generative 3D
│
└── Spatial Watchlist
      └── wait for ecosystem convergence
```

---

# 2. Context

Specialist OS currently implements or has accepted the following Core capabilities:

```text
VISION
├── detection
├── segmentation
├── OCR
├── semantic embedding / search
├── human landmarks
├── face identity
└── deterministic geometry

SPATIAL
└── monocular depth

SCREEN
└── UI parsing

DOCUMENT
└── structured parsing

SPEECH
├── VAD
├── ASR
├── diarization
├── TTS
└── voice cloning

AUDIO
└── denoise

MEDIA
└── deterministic processing
```

The currently selected Core providers include:

```text
YOLO
SAM
PaddleOCR
Depth Anything V2
OmniParser
MinerU
whisper.cpp
Silero VAD
Fish Audio
System TTS
MediaPipe
pyannote.audio
DeepFilterNet
OpenCLIP / SigLIP
InsightFace
OpenCV
FFmpeg
```

The Core has reached a point where it already covers the most important local specialist capabilities required by general-purpose LLMs.

The next proposed architectural expansion was originally:

> Spatial / 3D Intelligence.

This proposal included capabilities such as:

```text
camera pose
SfM
SLAM
point cloud
3D reconstruction
sensor fusion
coordinate frames
world maps
```

Potential providers included:

```text
Open3D
COLMAP / GLOMAP
RTAB-Map
GTSAM
AprilTag
VGGT
MoGe
```

However, after evaluating this direction against the product's core principles, Spatial / 3D does not currently satisfy the requirements for admission into Core.

---

# 3. Core Admission Criteria

A capability or Provider SHOULD enter Specialist OS Core only when most of the following are true:

## 3.1 Narrow-task superiority

The specialist must have a clearly defined task for which it is significantly more suitable than a general-purpose LLM/VLM.

Examples:

```text
OCR
→ PaddleOCR

VAD
→ Silero

Detection
→ YOLO
```

---

## 3.2 Developer production consensus

The project should have become a broadly recognized production primitive rather than merely a strong research implementation.

The relevant question is not:

> Is it SOTA on a paper benchmark?

The relevant question is:

> Would experienced developers independently reach for this tool when implementing this capability?

---

## 3.3 Laptop-first viability

The default Provider should run meaningfully on ordinary developer hardware.

Preferred target:

```text
Apple Silicon laptop
Windows laptop
Linux laptop/workstation
```

Heavy GPU infrastructure MAY be supported but SHOULD NOT be required for a Core primitive.

---

## 3.4 Stable capability semantics

The capability must have a reasonably stable abstraction.

Examples:

```text
ocr()
detect()
segment()
transcribe()
```

The API should remain meaningful even if the underlying model changes.

---

## 3.5 Tool-like behavior

The capability should behave like an instrument or system utility:

```text
input
→ specialist
→ measurable / structured result
```

rather than:

```text
prompt
→ generative model
→ subjective creative artifact
```

---

## 3.6 Mature deployment path

Preferred characteristics include:

```text
pip / uv / brew / native binary
CPU / MPS / ONNX / CUDA support
stable model distribution
predictable outputs
active maintenance
```

---

# 4. Why Spatial / 3D Fails the Current Core Test

Spatial / 3D currently consists of several very different technical domains that have not converged into one developer abstraction.

These include:

```text
monocular geometry
multi-view geometry
SfM
visual odometry
SLAM
sensor fusion
point-cloud processing
meshing
neural reconstruction
NeRF
Gaussian splatting
3D asset generation
```

Calling all of these:

```text
3D
```

creates a false abstraction.

---

# 5. Problem 1 — No Clear "YOLO of 3D"

There is currently no single project that simultaneously satisfies:

```text
SOTA
+
production consensus
+
laptop-first
+
cross-platform
+
stable API
+
broad developer adoption
```

for general 3D world understanding.

Instead the ecosystem is fragmented.

For example:

```text
Depth estimation
→ one ecosystem

SfM
→ another ecosystem

SLAM
→ another ecosystem

Neural reconstruction
→ another ecosystem

3D generation
→ another ecosystem
```

This is different from domains such as:

```text
OCR
Detection
ASR
VAD
```

where mature default primitives have emerged.

---

# 6. Problem 2 — Classical 3D Tools Are Excellent but Do Not Justify a New Core Domain

Projects such as:

```text
COLMAP
Open3D
GTSAM
RTAB-Map
OpenCV geometry
```

are mature and valuable.

However, they primarily represent:

```text
geometry libraries
robotics infrastructure
optimization frameworks
reconstruction systems
```

rather than the kind of:

```text
one narrow capability
→ one obvious specialist primitive
```

that currently defines Specialist OS Core.

They MAY eventually become Providers or Operators.

They do not currently justify creating an entire new Core abstraction.

---

# 7. Problem 3 — Geometry Foundation Models Are Still Moving Too Quickly

Emerging models may eventually collapse complex 3D pipelines into simpler abstractions:

```text
images
↓
geometry foundation model
↓
depth
camera pose
point map
surface normals
```

This direction is strategically important.

However, today's ecosystem still shows:

```text
rapid architecture changes
large model sizes
limited Mac support
GPU-heavy inference
research-centric releases
uncertain API convergence
```

Therefore Specialist OS SHOULD observe this category rather than prematurely standardize it.

---

# 8. Problem 4 — Generative 3D Is a Different Product Category

Models and services such as:

```text
Hunyuan3D
TRELLIS
Tripo
Meshy
```

primarily solve:

```text
text/image
→ generated 3D asset
```

This is fundamentally different from:

```text
image
→ measured world state
```

Generative 3D belongs conceptually with:

```text
image generation
video generation
music generation
speech generation
```

rather than:

```text
OCR
detection
depth estimation
geometry
```

Therefore Generative 3D MUST NOT be used as justification for creating a Spatial Core.

---

# 9. New Taxonomy

3D MUST be divided into two domains.

---

# 10. Domain A — Spatial Intelligence

Definition:

> Extract, estimate, reconstruct, or reason about the geometry of the real world.

Potential capabilities:

```text
spatial.geometry
spatial.camera_pose
spatial.reconstruct
spatial.slam
spatial.pointcloud
spatial.registration
spatial.measure
```

Examples of candidate technologies:

```text
MoGe
VGGT
COLMAP
Open3D
RTAB-Map
GTSAM
AprilTag
```

Status:

# WATCHLIST

Not Core.

---

# 11. Domain B — Generative 3D

Definition:

> Generate synthetic 3D assets from text, images, or other prompts.

Possible capability:

```text
generate.3d
```

Potential Providers:

```text
Hunyuan3D
TRELLIS
Tripo
Meshy
future providers
```

Status:

# OPTIONAL HEAVY PACK

Not Core.

---

# 12. Core Freeze Decision

The Core Capability Set SHALL be frozen at the existing production set.

No new Core domain SHOULD be added merely because:

```text
a strong paper appears
a famous lab releases a model
a benchmark reaches SOTA
a cloud service becomes popular
```

Future Core expansion requires evidence of ecosystem convergence.

---

# 13. Current Core Product Position

With the current capabilities, Specialist OS already provides:

```text
SEE
READ
SEGMENT
MEASURE DEPTH
UNDERSTAND UI
PARSE DOCUMENTS
HEAR
DISTINGUISH SPEAKERS
CLEAN AUDIO
SPEAK
UNDERSTAND HUMAN LANDMARKS
SEARCH VISUAL SEMANTICS
VERIFY FACES
CALCULATE GEOMETRY
PROCESS MEDIA
```

This represents a sufficiently coherent Core product:

# Machine Perception & Media Utility Layer

The product SHOULD optimize this layer before expanding into additional domains.

---

# 14. Depth Remains Core

Depth estimation remains an exception.

```text
spatial.depth
```

is already sufficiently mature and narrow to remain Core.

Reasons:

```text
clear capability semantics
laptop viability
useful structured output
strong specialist advantage
easy composition with detection/segmentation
```

Therefore:

```text
Depth Anything V2
```

remains a Core Provider.

However:

```text
depth
≠
complete 3D intelligence
```

The existence of depth capability MUST NOT imply that Specialist OS has committed to a complete Spatial stack.

---

# 15. Existing OpenCV Geometry Remains Core

Existing:

```text
vision.geometry.*
```

continues to provide deterministic geometry such as:

```text
distance
angle
homography
camera calibration
PnP
perspective transforms
triangulation
```

Where appropriate, individual 3D mathematical operations MAY be exposed through OpenCV without creating a dedicated Spatial Pack.

This allows incremental utility without prematurely committing to a full world-model architecture.

---

# 16. Spatial Watchlist

A formal Watchlist SHALL be created.

Initial projects/categories:

```text
MoGe family
VGGT family
geometry foundation models
local multi-view reconstruction models
local metric geometry models
local camera-pose models
```

The Watchlist SHOULD record:

```text
capabilities
parameter count
Mac support
MPS support
ONNX/CoreML availability
VRAM/RAM requirement
license
maintenance activity
downstream adoption
inference latency
output semantics
```

---

# 17. Promotion Criteria for Spatial Core

A Spatial capability MAY be promoted to Core when a Provider ecosystem demonstrates:

## Requirement A

A stable generic API such as:

```python
geometry = spatial.geometry(images)
```

or:

```python
pose = spatial.camera_pose(frames)
```

---

## Requirement B

Laptop-class execution is practical.

Target baseline:

```text
Apple Silicon
≤ reasonable unified memory
no mandatory 24GB NVIDIA GPU
```

---

## Requirement C

The implementation has moved beyond research-demo status.

Evidence MAY include:

```text
multiple production integrations
active packaging
cross-platform support
stable releases
community wrappers
downstream ecosystem usage
```

---

## Requirement D

Outputs have clear measurable semantics.

Examples:

```text
metric depth
point map
camera intrinsics
camera pose
surface normal
point cloud
```

Prefer structured geometry over:

```text
natural-language spatial description
```

---

## Requirement E

There is a recognizable default or narrow set of default Providers.

Specialist OS SHOULD NOT standardize an abstraction while the ecosystem is still split across fundamentally incompatible paradigms.

---

# 18. No Premature World Model

Specialist OS SHALL NOT currently implement:

```text
World Map
Transform Tree
Persistent Scene Graph
3D Entity Store
Spatial Database
Physical World SQL
```

as Core infrastructure.

These abstractions may eventually become valuable.

But implementing them before the underlying spatial Provider ecosystem stabilizes would introduce large amounts of architecture based on speculative future requirements.

---

# 19. Reasoning

A premature World Model would create dependencies on unresolved questions:

```text
What is the canonical coordinate system?
How are metric scales calibrated?
How are entities merged across frames?
How are SLAM failures represented?
How are point clouds stored?
How are moving objects represented?
How are uncertain poses modeled?
What is a persistent 3D entity?
```

These are legitimate robotics/spatial-computing problems.

They are not necessary to fulfill Specialist OS's current mission.

---

# 20. Generative Pack Decision

A separate optional namespace MAY be introduced:

```text
generate.*
```

Examples:

```text
generate.image
generate.video
generate.audio
generate.3d
```

This namespace is explicitly outside Specialist Core semantics.

---

# 21. `generate.3d`

Potential interface:

```python
generate.3d(
    prompt=None,
    image=None,
    profile="quality"
)
```

Potential output:

```text
3D Artifact
```

Possible formats:

```text
GLB
OBJ
USDZ
PLY
```

---

# 22. Heavy Provider Policy

Generative 3D Providers are expected to be:

```text
GPU-heavy
large-model
remote-capable
possibly cloud-only
```

Therefore:

```text
local-first
```

means:

> Prefer local when practical, but allow remote execution for inherently heavy optional providers.

It MUST NOT mean:

> Every optional generative model has to run efficiently on a laptop.

---

# 23. Generative 3D Provider Categories

Providers MAY include:

### Local Heavy

```text
Hunyuan3D
TRELLIS
future open-weight models
```

### Remote Self-hosted

```text
GPU Node
RunPod
Modal
own workstation
```

### Cloud API

```text
Tripo
Meshy
future APIs
```

All should implement the same optional capability:

```text
generate.3d
```

where semantically possible.

---

# 24. Core / Heavy Separation

The product MUST clearly differentiate:

```text
Core Capability
```

from:

```text
Heavy Optional Provider
```

Core properties:

```text
predictable
utility-oriented
local-friendly
tool-like
```

Heavy Pack properties:

```text
optional
large
creative/generative
GPU-heavy
potentially remote
```

---

# 25. Installation UX

Core:

```bash
specialist install core
```

MUST NOT install any Generative 3D dependencies.

Generative 3D:

```bash
specialist install generate-3d
```

or:

```bash
specialist provider install hunyuan3d
```

must be explicit.

---

# 26. Hardware Suitability

`specialist doctor` SHOULD display:

```text
Generative 3D
────────────────────────────
Local provider      unavailable / unsuitable
Reason              insufficient GPU memory

Available:
Remote Node         ✓
Cloud Provider      ✓
```

No Core health warning should be generated merely because 3D generation is unavailable.

---

# 27. Architecture Boundary

Core Runtime MAY support the generic infrastructure needed by heavy 3D providers:

```text
Artifact Store
Remote Compute Node
Provider Lifecycle
Model Cache
GPU Scheduling
Streaming Progress
```

But Core SHOULD NOT contain 3D-specific scheduling or world-model logic.

---

# 28. Optional 3D Artifacts

The generic Artifact system SHOULD be extended when necessary to support:

```text
model/gltf-binary
model/obj
application/usd
point-cloud artifacts
mesh artifacts
```

This extension is acceptable because Artifact types are generic infrastructure.

It does not imply adoption of Spatial Core.

---

# 29. Rendering Is Not Geometry Truth

Specialist OS SHALL distinguish:

```text
render-quality representation
```

from:

```text
metric geometric representation
```

For example:

```text
Gaussian Splat
NeRF
Generated mesh
```

MUST NOT automatically be treated as reliable geometric measurement sources.

Capability metadata SHOULD identify:

```text
semantic_type:
  generative
  reconstruction
  metric_geometry
  rendering
```

---

# 30. Model Output Semantics

A generated 3D asset may be:

```json
{
  "semantic_type": "generative_3d"
}
```

A metric reconstruction may later be:

```json
{
  "semantic_type": "metric_geometry",
  "unit": "meter"
}
```

These outputs MUST remain semantically distinct.

---

# 31. No Forced 3D Symmetry

The system SHOULD NOT attempt to create artificial symmetry across domains such as:

```text
vision.generate
audio.generate
video.generate
3d.generate
```

unless there is actual user demand.

The Generative Pack remains optional and provider-driven.

---

# 32. Roadmap Change

Previous roadmap:

```text
Core 15
↓
Spatial / 3D Pack
↓
World Representation
```

is cancelled.

New roadmap:

```text
Core 15
      │
      ├── Stability / Quality
      │
      ├── Provider Replacement
      │
      ├── Benchmarking
      │
      ├── Packaging
      │
      ├── Cross-platform
      │
      ├── Optional Specialist Packs
      │
      ├── Optional Generative Packs
      │
      └── Spatial Watchlist
```

---

# 33. Near-Term Priorities

Instead of creating a speculative Spatial architecture, near-term engineering SHOULD prioritize:

```text
Core capability reliability
Provider isolation
Apple Silicon optimization
model caching
installation quality
typed schemas
artifact interoperability
MCP / Harness integrations
benchmark corpus
provider replacement
streaming support
```

The product should become excellent at its current scope before increasing conceptual surface area.

---

# 34. Spatial Experimentation Policy

Experimental Spatial providers MAY still be developed.

They MUST live under:

```text
experimental/
```

or:

```text
packs/spatial-experimental/
```

and MUST NOT modify stable Core contracts.

Possible experimental capabilities:

```text
experimental.spatial.geometry
experimental.spatial.reconstruct
experimental.spatial.camera_pose
```

---

# 35. Experimental Promotion

An experimental Spatial capability can later graduate through:

```text
EXPERIMENTAL
↓
OPTIONAL PACK
↓
VERIFIED PACK
↓
CORE
```

Core promotion is intentionally difficult.

---

# 36. Why This Conservatism Is Valuable

Specialist OS's strongest property is not:

> It supports every AI model category.

Its strongest property is:

> Every capability it exposes has a clear reason to exist.

Adding immature 3D abstractions would weaken this signal.

A smaller, coherent Core is more valuable than a larger but conceptually inconsistent toolkit.

---

# 37. Updated Product Positioning

Specialist OS remains:

> **A local-first machine perception, media, and specialist computation layer for LLMs.**

It is not yet:

> A universal physical-world operating system.

That second positioning may become justified later.

It should not be claimed before the technology stack warrants it.

---

# 38. Updated Core Principle

The project SHALL follow:

```text
Wait for convergence.
Abstract after convergence.
```

Not:

```text
Predict the future abstraction
and force today's tools into it.
```

---

# 39. Trigger for Reopening This ADR

This ADR SHOULD be reconsidered if one or more Spatial foundation models achieve all of:

```text
strong geometry quality
metric outputs
camera pose support
laptop inference
Apple Silicon support
stable packaging
active developer ecosystem
multiple downstream production integrations
```

At that point, a new ADR should evaluate:

```text
spatial.geometry
```

as the first Spatial Core Capability.

---

# 40. Likely Future Entry Point

If Spatial eventually enters Core, the first capability SHOULD probably not be:

```text
slam
```

or:

```text
3d.generate
```

The likely first abstraction is:

```text
spatial.geometry
```

with output resembling:

```text
depth
point map
surface normals
camera intrinsics
optional camera pose
```

because this is the most natural extension of the existing:

```text
spatial.depth
```

capability.

---

# 41. Final Architecture

```text
                         Specialist OS

                         ┌────────────┐
                         │  Core 15   │
                         └─────┬──────┘
                               │
            ┌──────────────────┼────────────────────┐
            │                  │                    │
            ▼                  ▼                    ▼
     Specialist Packs    Generative Packs     Spatial Watchlist
            │                  │                    │
       QR / Metadata       Image / Video       MoGe / VGGT
       Background etc.     Audio / 3D          Future Models
                               │
                               ▼
                       Heavy / Remote OK

Core remains:
local-first
stable
tool-like
production-oriented
```

---

# 42. Consequences

## Positive

This decision:

* preserves Core coherence;
* avoids speculative architecture;
* avoids introducing GPU-heavy dependencies into default installs;
* prevents generative 3D from contaminating perception semantics;
* preserves laptop-first positioning;
* allows experimentation without API lock-in;
* leaves room to adopt future geometry foundation models when the ecosystem converges.

---

## Negative

Specialist OS will temporarily lack:

```text
full 3D reconstruction
SLAM
world maps
point-cloud intelligence
3D generation
```

as first-class Core capabilities.

Users requiring these capabilities must use experimental or optional providers.

This is accepted.

---

# 43. Final Decision

**ACCEPT.**

The Specialist OS Core Capability Set is frozen at the current production scope.

Spatial / 3D SHALL NOT become the next Core domain.

Instead:

```text
Real-world Spatial Intelligence
→ Watchlist / Experimental

Generative 3D
→ Optional Heavy Generative Pack
```

Depth estimation and deterministic camera/geometry operators remain Core where already implemented.

A future Spatial Core expansion SHALL occur only after the ecosystem develops a clear production-grade, laptop-friendly geometry primitive.

The architectural principle is:

> **Do not create a Core abstraction before the ecosystem has earned one.**

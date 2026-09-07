# Core scope and roadmap

Specialist OS is a local-first machine perception, media, and specialist
computation layer for LLMs. [ADR-003](adr/003-defer-spatial-3d-core.md) freezes
product scope while providers, packaging and execution quality improve.

## Core 15

Core 15 means **15 product capability families**, not 15 CLI methods or models.
The baseline contains 56 APIs, including operators and compositions.
`specialist/core.py` owns explicit membership. Registry discovery exposes
`core` and `core_family`. New registrations do not automatically join Core.
Membership describes product scope, not readiness on a particular machine.

| Family | Existing capability surface |
| --- | --- |
| Detection | `vision.detect` |
| Segmentation | `vision.segment` |
| OCR | `vision.ocr` |
| Depth | `vision.depth`, also resolved by `spatial.depth` |
| Screen | `screen.parse` |
| Document | `document.parse` |
| Speech recognition | `audio.transcribe`, `audio.vad` |
| Diarization | `speech.diarize`, transcript alignment and meeting composition |
| Denoise | `audio.denoise` |
| Speech generation | `speech.synthesize`, `speech.clone_voice` |
| Human landmarks | `human.*`, `vision.human_state` |
| Visual search | Image/text embeddings, similarity, search and find-similar |
| Face identity | `identity.face.*`, `vision.face_compare` |
| Geometry | Existing `vision.geometry.*`, `vision.transform.*`, `vision.measure` |
| Media | Existing `media.*` operations and video transcription |

Prefixes summarize the baseline; they are not wildcard admission rules.
Provider replacement within these contracts is welcome. Expansion requires a
new reviewed ADR and evidence against the Core admission criteria.

## Installation and compatibility

`specialist install core` and `specialist pack install core` select only the
frozen baseline. Neither installs generative 3D dependencies. Provider setup
remains on demand. Fish Audio deployment requirements remain independent;
Core membership does not make every provider lightweight.

The former `spatial` pack is listed as `depth-vision`, describing its depth,
detection and segmentation APIs. `specialist pack install spatial` remains a
compatibility alias. `spatial.depth` still resolves to `vision.depth`.

## Separate expansion tracks

| Track | Admission and execution |
| --- | --- |
| Stable Core | Current 15 families, local-friendly utility contracts |
| Optional specialist packs | Explicitly selected task extensions |
| Spatial watchlist | Evaluation only; isolated experimental providers |
| Optional heavy generative packs | Future explicit providers, local GPU, self-hosted or cloud where practical |

The [spatial watchlist](spatial-watchlist.md) records evidence for promotion.
Experiments belong in `experimental/` or `packs/spatial-experimental/` and use
`experimental.spatial.*`. They cannot alter stable Core contracts. Promotion
proceeds through experimental, optional pack, verified pack, then Core review.

Generative 3D is a reserved direction, not an installed pack in this release.
`generate.3d`, `generate-3d`, and Hunyuan3D/TRELLIS/Tripo/Meshy providers are not
registered. Installing these targets fails rather than reporting success.
Doctor checks registered providers, so absent 3D generation causes no Core
warning. Future optional health must remain separate and only list remote/cloud
routes actually configured. Future heavy installation must be explicit and
must not enter the Core target or its aliases.

Generic artifact storage and lifecycle code can be reused. Add mesh MIME support
only with a concrete provider contract and interoperability tests.

## Geometry semantics

Depth Anything V2 supplies relative monocular depth, not calibrated meters.
Existing OpenCV operators retain their current schemas. Calibration and PnP do
not imply a persistent world map. Triangulation mentioned as a possible operator
in ADR-003 is not a registered API in this baseline.

Future outputs must distinguish `generative_3d`, `rendering`, `reconstruction`
and `metric_geometry`. A generated mesh, NeRF or Gaussian splat cannot acquire
measurement semantics from its file format. Metric outputs need explicit units,
coordinate conventions, scale calibration and validation evidence. These future
semantics do not change current result payloads.

## Roadmap

Near-term work focuses on reliability, provider isolation, Apple Silicon
performance, caching, installation quality, typed schemas, artifact
interoperability, MCP integrations, benchmarks, provider replacement and streaming.
Spatial expansion and world representation are deferred. World maps, transform
trees, persistent scene graphs, 3D entity stores and spatial databases are outside
the current Core plan.

Reopen when a provider combines measurable metric output and camera pose with
practical laptop/Apple Silicon inference, stable packaging, active maintenance
and multiple production integrations. The first candidate abstraction is
`spatial.geometry`, subject to that review.

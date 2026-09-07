# Design

Keep registry and runtime as the execution owners. Add compact filtered discovery
before runtime construction. Add JSON batch requests executing sequentially in
one runtime, preserving worker reuse and the existing result envelope. The skill
uses uv installation, targeted discovery, real isolated inference, and batch
execution for repeated work. Use existing full-gallery runner for complete
rehearsal and provide a shorter live route. Slides use saved real artifacts.

Experimental 3D evaluation uses an explicit CLI branch outside the frozen
registry and Core install targets. Keep inference implementations under an
experimental namespace, imports lazy, and use isolated prepared environments.
TripoSR is the initial image-to-asset candidate, MoGe 2 the initial scene
geometry candidate. Output envelopes preserve semantic_type and actual device,
with viewable mesh/point artifacts and raw arrays where appropriate. Existing
OpenCV geometry continues through its current Runtime contract. A local
Three.js page reads exported artifacts and offers rotation/zoom and input
comparison. Failure produces an error record, never a substitute shape.

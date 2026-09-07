# Design

Keep an explicit immutable family-to-capability baseline in specialist/core.py.
Registry bundle construction and discovery consume this owner. New registry
entries do not join Core implicitly. Existing API names and payloads stay intact.
Rename the misleading spatial catalog pack to depth-vision and resolve spatial
as a compatibility alias. Do not advertise unavailable generation providers.

Record the accepted source ADR verbatim under docs/adr. Separate policy and
watchlist evaluation records from executable model registration. Future heavy
providers require explicit installation and separate suitability reporting;
no world-model infrastructure or speculative MIME/schema expansion is needed.

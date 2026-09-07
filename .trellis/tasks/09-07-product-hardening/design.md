# Design

Use pytest for both unittest classes and pytest functions, installing test-only
dependencies in CI. Keep optional inference opt-in. Test shell serialization
against a real POSIX shell using inert print arguments. Remove unused controls
from the read-only evidence inspector, retain exact run provenance and display
the serialized command. Apply channel conversion independently of sample-rate
conversion. Keep broader execution-workspace changes separate from these fixes.

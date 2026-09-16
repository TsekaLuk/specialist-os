# Design

Use pytest for both unittest classes and pytest functions, installing test-only
dependencies in CI. Keep optional inference opt-in. Test shell serialization
against a real POSIX shell using inert print arguments. Remove unused controls
from the read-only evidence inspector, retain exact run provenance and display
the serialized command. Apply channel conversion independently of sample-rate
conversion. Keep broader execution-workspace changes separate from these fixes.

Carry provider prerequisites as data beside the provider so they can be read
without importing provider code, with interchangeable sources sharing a group
label. Probe by kind and leave endpoints unprobed by default, so a configured
but offline remote node cannot stall the report. Keep the existing status values
and add a degraded level for an installed, routable capability with an unmet
non-optional prerequisite, carrying the reason into human output.

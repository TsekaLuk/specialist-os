# DeepSeek Harness adapter

The runtime stays model-agnostic. This directory documents the adapter boundary
for DeepSeek Harness integrations: register the JSON schemas exposed by
`specialist serve --mcp` or call the HTTP endpoints under `/v1/`.

No model inference belongs in this adapter. It should only translate tool names,
arguments and serialized result envelopes.


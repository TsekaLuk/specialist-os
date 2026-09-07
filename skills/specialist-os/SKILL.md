---
name: specialist-os
description: Process local images, documents, screens, speech and media with Specialist OS. Use for detection, segmentation, OCR, transcription, depth, landmarks, visual retrieval, measurement and media conversion, or combining these into an agent workflow.
---

# Specialist OS

Turn the user's local files into useful visual, textual or audio results. Use
the installed registry to discover capabilities and execute with real providers.

## First use

Run `specialist --version`. If missing, use a current local checkout when one is
available: `uv tool install --python 3.12 /absolute/path/to/specialist-os`. Otherwise install
the published repository with `uv tool install --python 3.12 git+https://github.com/TsekaLuk/specialist-os.git`.
Python 3.10+ and uv are prerequisites. Do not install all model packs up front.

Run `specialist capabilities --compact` once. Retrieve details only for the
selected capability: `specialist capabilities vision.ocr`. This includes input
and output schemas, model disk/memory estimates, supported devices and licensing.
Use `specialist --backend real explain vision.ocr --json` to inspect routing.

## Local execution

For a requested capability, install its dependencies and verified weights with
`specialist --backend real --with-dependencies install vision.ocr` on first use.
Report model preparation separately from inference. Reuse the existing installation
on subsequent calls. Downloads are local and on demand. Follow structured install
errors for missing system tools, credentials or unsupported hardware.

Execute `specialist --backend real --isolate ocr /absolute/input.png --json`.
Replace `ocr` with the registry command. Read its `--help` for positional arguments.
Use `--options` for a JSON object matching the capability schema. Prefer absolute
paths. Do not infer a successful result from process exit alone: inspect `error`,
warnings, degraded status, provider and model.

## Efficient workflows

For consecutive calls, create a JSON list and run
`specialist --backend real --isolate --max-loaded 2 batch /absolute/requests.json`.
Each item has `capability`, `input`, and optional `options`. Workers stay loaded
within the batch. Group repeated capabilities together. Batch stops on the first
error unless `--keep-going` is requested. Inputs resolve relative to the working
directory. Use SDK graphs for dynamic dependencies between results.

For interactive use across many agent turns, prefer the existing persistent MCP
server: `specialist --backend real --isolate serve --mcp`. Read
[integration.md](references/integration.md) when configuring MCP or building an app.

## Deliver results

Return the result relevant to the user's goal, not the complete diagnostic envelope.
Resolve output artifact URIs using the SDK ArtifactStore before displaying local
images/audio or linking files. Preserve result JSON alongside delivered artifacts.
Distinguish input recordings from generated audio. For recognition, show transcript
or detected intervals alongside the input. For benchmarks disable result caching
with `options.no_cache=true`, and separate cold from warm inference.

Fish Audio runs through a local S2 server; its server weights and environment need
separate provisioning. Follow `specialist provider status fish_audio` and the
repository deployment guide. Do not silently switch to a remote service or another
voice provider. Voice cloning requires the user's intended reference recording.

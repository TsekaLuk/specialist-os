# Quality Guidelines

> Code quality standards for backend development.

---

## Overview

<!--
Document your project's quality standards here.

Questions to answer:
- What patterns are forbidden?
- What linting rules do you enforce?
- What are your testing requirements?
- What code review standards apply?
-->

(To be filled by the team)

## CLI Capability Gallery Contract

### 1. Scope / Trigger

This contract applies to `scripts/generate_readme_gallery.py`, its generated
files under `docs/assets/e2e/`, and any README media links. Gallery output is a
release-facing record of local CLI execution, so it must remain reproducible
and must never invent a provider result.

### 2. Signatures

```text
python scripts/generate_readme_gallery.py \
  --python <provider-python> \
  --home <specialist-home> \
  --backend real|auto|fallback \
  [--timeout-seconds <float>] \
  [--allow-errors] [--skip-optional]
```

The default per-capability timeout is 180 seconds. `--allow-errors` records a
structured failure and continues; without it, the first provider failure stops
the run.

### 3. Contracts

- Every capability call is made through `python -m specialist --isolate ...`
  with the selected backend and JSON output.
- `capability-gallery.json.records[capability].status` is `ok`, `degraded`, or
  `error`. A `degraded` result is a valid envelope with an unavailable child;
  it is never rendered as a showcase tile.
- Binary outputs are copied from `artifact://` URIs in the local content-
  addressed store. README audio uses HTML5 `<audio controls>` with a matching
  `<source type>` and a direct file link.
- Audio output extensions are derived from the CLI result MIME (`audio/flac`
  produces `.flac`, not `.wav`). Compressed audio previews may be decoded to
  PCM by FFmpeg for the contact sheet; the served artifact remains unchanged.
- The manifest retains provider, model, input hash, and structured error data.

### 4. Validation & Error Matrix

| Condition | Result |
| --- | --- |
| CLI returns valid envelope without error or degraded status | `ok`, eligible for a tile |
| Envelope result has `status=degraded` | `degraded`, retained in manifest, no tile |
| Provider returns structured error | `error`, retained in manifest, no tile |
| CLI exceeds timeout | `error` with `provider_timeout`; terminate the complete process group |
| Artifact URI is malformed or missing | fail the gallery build; do not copy a substitute |
| Audio MIME and file suffix disagree | use the result MIME to choose the showcase suffix |

### 5. Good / Base / Bad Cases

- Good: `--backend real` runs YOLO, stores its provider/model and input SHA,
  and renders the five detections returned by the CLI.
- Base: an unavailable optional Provider is recorded as `error` and the grid
  still contains only successful capabilities.
- Bad: drawing a detection, waveform, transcript, or speaker label directly
  in the gallery script without a corresponding successful CLI envelope.

### 6. Tests Required

- Run unit and E2E suites, `compileall`, and `scripts/release_check.py
  --require-artifacts` before committing gallery changes.
- Check that every manifest JSON and listed audio file exists.
- Check representative envelopes for provider/model/input SHA and no fallback
  warning when `backend=real`.
- Check `audio/flac` output is saved as `.flac` and is playable through the
  README `<audio>` source.

### 7. Wrong vs Correct

#### Wrong

```python
tiles.append(_tile(_waveform(audio), "Video transcription", text))
```

when `text` came from a different input or the CLI result is degraded.

#### Correct

```python
payload = result.get("result") or {}
if not result.get("error") and payload.get("status") != "degraded":
    tiles.append(_tile(_json_card(payload), "Video transcription", payload.get("text", "")))
```

The tile is derived only from the same successful result envelope.

---

## Verified Model Download Contract

### 1. Scope / Trigger

This contract applies whenever `ModelManager` downloads a registry model file
or a file inside a model bundle. Model payloads are executable inputs, so a
transport success response is never sufficient proof that a model is ready.

### 2. Signatures

```python
ModelManager(
    cache,
    timeout=60,
    max_bytes=20 * 1024**3,
    download_attempts=5,
).download(url, destination, expected_sha256)
```

`url` must use `https://`, `http://`, or `file://` and
`expected_sha256` must be exactly 64 hexadecimal characters.

### 3. Contracts

- The destination is replaced atomically only after the complete temporary
  payload passes SHA256 verification.
- A truncated remote response is retried. When partial bytes exist, the next
  request sends `Range: bytes=<current-size>-`.
- A `206` response is appended only when its `Content-Range` starts at the
  requested byte and declares the final total size. A normal `200` response
  replaces the partial payload.
- `Content-Length` or the total in `Content-Range` is checked against both the
  actual byte count and `max_bytes`.
- If a complete payload has the wrong SHA256, the temporary file is cleared
  before retrying from byte zero. Corrupt bytes must never be resumed.
- HTTP error bodies may be read only to a bounded diagnostic limit, and the
  `HTTPError` response must be closed before retrying or raising.
- The default retry budget is five attempts with bounded exponential backoff.

### 4. Validation & Error Matrix

| Condition | Result |
| --- | --- |
| Missing or malformed SHA256 | `ModelArtifactError`; no request is made |
| HTTPS redirects to HTTP | `ModelArtifactError`; destination is unchanged |
| Truncated response with attempts remaining | Preserve partial file and issue a Range request |
| Invalid `Content-Range` or payload exceeds `max_bytes` | `ModelArtifactError`; destination is unchanged |
| HTTP 408/416/425/429 or 5xx | Retry; reset partial data on 416 |
| Other HTTP error | Fail immediately with `ModelArtifactError` |
| Complete payload has the wrong SHA256 | Clear partial data and retry from byte zero |
| Verified payload | Atomically replace destination and return path, size, SHA256, and source |

### 5. Good / Base / Bad Cases

- Good: a connection closes after eight bytes, the server honors the Range
  request, and the reconstructed payload passes SHA256 before installation.
- Base: a server ignores Range and returns `200`; overwrite the partial file
  and validate the new complete response.
- Bad: append a new `200` response to partial bytes, or publish a destination
  after checking only its reported length.

### 6. Tests Required

- Use a local HTTP server that first truncates a response, then serves corrupt
  resumed bytes, then serves the complete valid payload.
- Assert request Range headers are `[None, "bytes=8-", None]`.
- Assert the final destination equals the expected payload and its returned
  SHA256 equals the registry checksum.
- Keep bundle atomicity and post-install tamper detection tests green.
- Run HTTP failure-path tests with `ResourceWarning` promoted to an error.

### 7. Wrong vs Correct

#### Wrong

```python
urllib.request.urlretrieve(url, destination)
cache.mark_installed(destination)
```

#### Correct

```python
artifact = ModelManager(cache).download(
    model.artifact_url,
    destination,
    expected_sha256=model.artifact_sha256,
)
cache.mark_installed(artifact_path=artifact["path"], sha256=artifact["sha256"])
```

The cache records a model only after verified bytes are atomically visible.

---

## Forbidden Patterns

<!-- Patterns that should never be used and why -->

(To be filled by the team)

---

## Required Patterns

<!-- Patterns that must always be used -->

(To be filled by the team)

---

## Testing Requirements

<!-- What level of testing is expected -->

(To be filled by the team)

---

## Code Review Checklist

<!-- What reviewers should check -->

(To be filled by the team)

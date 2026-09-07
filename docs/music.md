# Music Intelligence

Music capabilities turn recordings into searchable descriptors and editable
musical material. A media library can filter by tempo and key, compare recording
fingerprints, or send an audio transcription into a MIDI workflow.

音乐能力把录音变成可检索的素材信息和可编辑的音乐数据。素材库可以按节奏与
调性选曲、核对同源录音，也可以把音频转写成 MIDI，继续编曲或制作练习素材。

## Available CLI Paths

| Capability | Provider | Output |
| --- | --- | --- |
| `music.analyze` | Essentia | Tempo, beats, key, loudness and optional descriptors |
| `music.fingerprint` | Chromaprint | Recording fingerprint |
| `music.compare_recording` | Chromaprint | Aligned recording comparison |
| `music.transcribe_notes` | Basic Pitch | Note events and MIDI |
| `music.separate` | audio-separator | Vocals and instrumental WAV stems |
| `music.transcribe_multitrack` | MuScriptor | Instrument-attributed notes, full and per-track MIDI |
| `music.transcribe_vocal` | ROSVOT | Sung note events and melody MIDI |
| `music.generate` | ACE-Step 1.5 | Generated WAV from a prompt file |
| `music.parse_singing` | Composite | Lyrics, vocal notes, analysis and temporal associations |
| `music.transcribe_full` | Composite | Multitrack transcription, separation and per-stem refinement |

All ten paths have successful local CLI evidence. Seven analysis/transcription
paths use the same licensed recording; two workflows retain every child result.
Generation uses its own prompt input. Music stays outside Core 15 / 56 APIs.

```bash
specialist --backend real --with-dependencies install music.analyze
specialist --backend real --with-dependencies install music.transcribe_notes
specialist --backend real --isolate music-analyze /absolute/music.ogg --json
specialist --backend real --isolate music-transcribe-notes /absolute/music.ogg --json
```

Chromaprint requires the system `fpcalc` executable, version 1.6.1. Basic Pitch
uses a separate Python 3.11 environment. Weight downloads are verified and local.

## Live Demo

Run from this checkout with the provider environments prepared:

```bash
.venv/bin/python scripts/rehearse_music_workflows.py \
  output/music-singing-rehearsal/singing.ogg \
  --home output/music-rehearsal/home --output output/music-workflow-rehearsal
```

The listening page is `output/demo/music-singing/index.html`. It plays the input and stems,
visualizes single-instrument and multitrack note events, and provides MIDI and JSON downloads.
`manifest.json` records the exact CLI commands and input identity. Serve
`output/demo` with byte-range support for audio seeking:

```bash
.venv/bin/python scripts/serve_demo.py --port 8744
```

Open `http://127.0.0.1:8744/music-singing/index.html` for the complete music demo,
including generation and both workflows. The instrumental jazz comparison
remains at `http://127.0.0.1:8744/music/index.html`.

The complete demo uses Karissa Hobbs' **Let's Go Fishin'**, a 132.99-second
recording licensed under CC BY 3.0. It includes playable vocals and accompaniment,
ROSVOT melody notes, six MuScriptor tracks, and the composite outputs. A separate
15-second ACE-Step cue with reference audio, 100 BPM and C major conditioning
took 36.94 seconds on local MPS with prepared
weights. The singing parser took 32.20 seconds; the full workflow took 141.83
seconds. These are individual uncached runs, not comparative quality scores.

```bash
.venv/bin/python scripts/build_music_showcase.py \
  --source output/music-singing-rehearsal \
  --output output/demo/music-singing \
  --generation output/music-generation-controls \
  --workflows output/music-workflow-rehearsal
```

Source: [Let's Go Fishin' by Karissa Hobbs](https://freemusicarchive.org/music/Karissa_Hobbs/Age_of_Flowers/09_Lets_Go_Fishin).

The Vibe Ace rehearsal returned 129.7 BPM, E major and 380 Basic Pitch note
events. MuScriptor returned electric bass (262 notes), electric piano (478),
and drums (323), with full and individual MIDI files. This local MPS run took
31.29 seconds and the CPU separation run took 16.97 seconds, excluding model
downloads. These describe one run, not annotated accuracy scores.
Source: [Vibe Ace by Kevin MacLeod](https://freemusicarchive.org/music/Kevin_MacLeod/Jazz_Sampler/Vibe_Ace),
[CC BY 3.0](https://creativecommons.org/licenses/by/3.0/).

## Installation and Licensing

`music`, `music-experimental` and `music-generation` are separate install packs.
With `--with-dependencies`, pack installation prepares isolated runtimes and
leaves large weights for first use. Install a single capability explicitly to
prepare its weights before a live session. `doctor` groups Music readiness by
Stable, Experimental and Heavy Generative.

MuScriptor weights require model access approval and use CC BY-NC 4.0 with additional terms.
Essentia uses AGPL or a commercial license. Check provider licenses for the
intended deployment independently of this project's MIT license.

## Generation Controls

```bash
.venv/bin/python scripts/rehearse_music_generation.py \
  tests/fixtures/music/generation-prompt.txt \
  --home output/music-rehearsal/home --output output/music-generation-controls \
  --python output/music-research/ace-env/bin/python --device mps \
  --bpm 100 --key 'C major' --reference-audio output/music-rehearsal/vibe-ace.ogg
```

The public capability accepts a prompt file, duration, seed, lyrics, instrumental
mode, BPM, key and a local reference recording. BPM/key are generation controls,
not measurements of the generated audio. The rehearsal retains input hashes,
CLI invocation and the complete result.

## Regression Recordings

The [local regression snapshot](music-regression.json) records 72 successful
uncached CLI runs across twelve fixture categories and six capabilities.

`tests/fixtures/music/benchmark.json` defines twelve fixture categories with
source URLs, licenses, attribution and pinned input hashes. Run the regression
workflow after installing the selected providers:

```bash
uv run --no-project --with libarchive-c python scripts/benchmark_music.py \
  --python .venv/bin/python --home output/music-rehearsal/home
.venv/bin/python scripts/benchmark_music.py --home output/music-rehearsal/home \
  --capability music.separate --capability music.transcribe_multitrack \
  --capability music.transcribe_vocal
```

The first run downloads source recordings and prepares short excerpts. FFmpeg
is required. The report retains every real isolated CLI envelope and latency.
Coverage includes piano, guitar, bass, clean vocals, accompanied vocals, pop,
rock, electronic arrangement, classical, jazz, variable tempo and a controlled
8 kHz degradation of a real recording. The last category tests bandwidth loss,
not microphone or room noise. Original MUSDB stems serve as inputs, never as
our separator's outputs. These short regression cases check execution and output
contracts; annotated accuracy and broad genre quality require larger evaluation.

## Presentation

The AHA deck embeds source/result audio on the speech and Music workflow pages.
MP3 listening derivatives travel inside the PPTX; the demo retains original WAV
and MIDI artifacts. See `docs/demo-runbook.zh-CN.md` for the speaking sequence.

[Download the presentation](slides/Specialist-OS-AHA-v5.pptx) and
[speaker notes](slides/Specialist-OS-AHA-v5-Speaker-Notes.md).

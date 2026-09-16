# CLI Demo Video

The recording follows actual local CLI execution into delivered results:
object detection, segmentation and depth, speech transcription and denoising,
then vocal and instrumental separation. It runs at normal speed with prepared
models and result caching disabled.

[Play or download the video](assets/demo/specialist-os-e2e.mp4)

[Launch mix with BGM](assets/demo/specialist-os-launch.mp4) ·
[Standalone BGM](assets/demo/specialist-os-launch-bgm.mp3)

The launch mix adds locally generated ACE-Step instrumental music. The music
fades out during speech and stem comparisons so the demonstrated audio remains
clear. The original video remains available above.

The video contains process output streamed during execution and browser footage
of the corresponding results. Audio excerpts use the same files and playback
positions shown by the players. No microphone or desktop audio is captured.

## Reproduce

Start the local demo server on port 8744. Prepare the provider environments and
source fixtures described in the [demo runbook](demo-runbook.zh-CN.md).
The music recording uses the existing Python 3.11 environment under
`output/music-research/separator-env` and model home `output/music-rehearsal/home`.

```bash
npm ci --prefix scripts/demo-video
python3 scripts/serve_demo.py --port 8744
```

In another terminal, set `PLAYWRIGHT_MODULE` to the installed Playwright package
when it is not available on Node's module search path. Set
`REMOTION_BROWSER_EXECUTABLE` to an installed headless Chromium executable to
reuse it instead of downloading another browser.

```bash
node scripts/demo-video/record.mjs
node scripts/demo-video/record-playback.mjs output/demo/recordings/<run>/manifest.json
node scripts/demo-video/render.mjs output/demo/recordings/<run>/manifest.json
```

Each recording directory retains full CLI envelopes, exact argument arrays,
timestamped process output, original WebM footage, playback positions and the
Remotion edit manifest. Failed inference stops the recording. A recording does
not replace the full capability test suite.

## Audio Credit

Music: Karissa Hobbs, *Let's Go Fishin'*, CC BY 3.0. The source fixture and its
attribution are retained in the Music rehearsal manifest. The video plays the
original, vocals and instrumental at the same position in the recording.

# Gallery inputs

These inputs are the public fixtures used by `scripts/generate_readme_gallery.py`.
The output tiles and JSON envelopes are produced locally by the Specialist CLI.

| File | Source |
| --- | --- |
| `bus-input.jpg` | Ultralytics public image asset, [bus.jpg](https://www.ultralytics.com/images/bus.jpg) |
| `boats-input.jpg` | Ultralytics public image asset, [boats.jpg](https://ultralytics.com/images/boats.jpg) |
| `ocr-table.png` | PaddleOCR TableBank demo image, [005.png](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/datasets/images/tablebank_demo/005.png) |
| `person-input.jpg`, `hand-input.jpg` | MediaPipe gesture recognizer test data |
| `specialist-github-screen.png` | Headless Chrome capture of the live [Specialist OS GitHub repository](https://github.com/TsekaLuk/specialist-os), used as a dense real-world UI input for OmniParser |
| `brief-input.pdf` | MinerU document demo, [demo3.pdf](https://github.com/opendatalab/MinerU/blob/master/demo/pdfs/demo3.pdf) |
| `audio-source.wav` | whisper.cpp sample, [jfk.wav](https://github.com/ggerganov/whisper.cpp/blob/master/samples/jfk.wav) |
| `meeting-two-speaker.wav` | Locally assembled four-turn incident review using the macOS Samantha and Daniel voices, 16 kHz mono PCM |
| `meeting-two-speaker-noisy.wav` | The same meeting mixed locally with seeded pink noise for the DeepFilterNet denoise result |
| `video-input.mp4` | Blender Foundation Big Buck Bunny trailer via [W3C media examples](https://media.w3.org/2010/05/bunny/trailer.mp4) |

The source files remain unchanged during a gallery run. CLI outputs are copied
from the local content-addressed artifact store into the adjacent showcase
files, and every JSON envelope keeps its provider and model provenance. The
manifest keeps `ok`, `degraded`, and `error` statuses; only `ok` results become
visual tiles.

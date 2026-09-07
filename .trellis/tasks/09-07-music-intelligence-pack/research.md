# Upstream Verification / 2026-09-07

- Essentia 2.1b6.dev1389 installs on local Python 3.12 / Apple Silicon.
  RhythmExtractor2013, KeyExtractor, LoudnessEBUR128, OnsetRate,
  TuningFrequencyExtractor, HPCP and MFCC were exercised through isolated CLI.
- Chromaprint 1.6.1 installed through Homebrew. The install also upgraded
  FFmpeg, mpg123 and x265. Native CLI fingerprint repetition, identity
  comparison and secondary-input cache invalidation tests pass.
- Basic Pitch 0.4.0 with ONNX installs on isolated Python 3.11. It requires
  setuptools 80.9.0 for its pkg_resources import. A real CLI run generated
  notes and a MIDI artifact from Vibe Ace. ONNX source is pinned to Spotify
  commit fa5997af0a8210982619003269994a1be25eddf3 and SHA256 in registry.
- audio-separator 0.30.2 dependency resolution succeeded (dry run only).
  Its upstream runtime downloads mutable model indexes/configs as well as
  weights; all required files must be pinned before enabling the adapter.
- MuScriptor official source: https://github.com/muscriptor/muscriptor.
  On Chrome, the medium model page is authenticated but still shows the
  access form. It requires CC BY-NC 4.0 plus supplemental terms and sharing
  the account email and username with authors. User must submit this form.
  CLI HF credentials were absent at the initial check. No tokens were read.
- ROSVOT official source: https://github.com/RickyL-2000/ROSVOT.
  Upstream tested Python 3.9 / torch 2.1.1 / CUDA 11.8. Weights are a Google
  Drive archive containing ROSVOT, RWBD and RMVPE. Not installed or run yet.
- ACE-Step 1.5 official source: https://github.com/ace-step/ACE-Step-1.5.
  Upstream documents Python 3.11-3.12 and MPS/MLX support. Not installed or
  run yet; no hardware performance claims have been verified locally.

## Fixture Evidence

Vibe Ace by Kevin MacLeod, CC-BY-3.0, obtained from librosa's audio mirror.
The source hash matches librosa's published registry. See
scripts/rehearse_music.py for the attribution, checksum and real CLI commands.
This is one jazz fixture, not the 12-category benchmark required by the ADR.
No ground-truth BPM, key or MIDI annotations were supplied, so no accuracy
metrics are claimed. Earlier speech input runs were plumbing checks only.

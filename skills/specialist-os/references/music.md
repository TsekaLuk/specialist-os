# Music Tasks

Discover the installed Music capabilities before execution. The namespace extends
Core without changing its baseline. Select by the user's intended output:

| Goal | Capability | Deliver |
| --- | --- | --- |
| Tempo, key, loudness or beat positions | `music.analyze` | Compact descriptors and requested arrays |
| Vocals or accompaniment | `music.separate` | Playable stem audio |
| Same-recording comparison | `music.compare_recording` | Match score, with `other_input` |
| Single instrument or simple polyphony to MIDI | `music.transcribe_notes` | Note events and MIDI |
| Instrument-attributed full mix to MIDI | `music.transcribe_multitrack` | Full and per-instrument MIDI |
| Reusable recording identity | `music.fingerprint` | Fingerprint and duration |
| Singing melody to MIDI | `music.transcribe_vocal` | Vocal notes and melody MIDI |
| A new music cue | `music.generate` | Playable generated WAV |
| Lyrics, melody and musical structure | `music.parse_singing` | Child results and timed associations |
| Full mix with stem refinements | `music.transcribe_full` | Multitrack MIDI, stems and per-stem notes |

Install only the chosen capability. Basic Pitch and audio-separator use Python
3.11 environments; MuScriptor uses Python 3.12. MuScriptor medium supports
`profile=balanced`; choose an advertised device explicitly when acceleration
matters. Weights require Hugging Face access approval and carry non-commercial
terms. Keep credentials in the user's local credential mechanism, not prompts.
Check Essentia and separation-checkpoint licensing for the target deployment.

ROSVOT is installed independently in `music-experimental`; ACE-Step belongs to
`music-generation`. Prefer capability-level installation when preparing a demo:
pack installation defers weights until use. A ready environment alone does not
mean model weights are present. MuScriptor download uses local Hugging Face
credentials (`HF_TOKEN` or the standard Hugging Face token file); browser login
alone does not authenticate the CLI.

For generation, input is a UTF-8 prompt file of at most 512 characters. Options
include `duration` (10..120 seconds), `seed` (uint32), `instrumental`, `lyrics`,
`bpm` (integer 30..300), `key` (for example `C major` or `Bb minor`), and
`reference_audio` (an explicit local mono/stereo file of at most 120 seconds).
These guide generation; measure the output when the user needs an exact tempo
or key. The current provider accepts no nonempty `provider_options` overrides.
Select a supported device from discovery; allow time for heavyweight generation.

Composites run their children through the same runtime. `music.parse_singing`
includes speech transcription, vocal notes and analysis; `music.transcribe_full`
includes separation, multitrack notes and stem refinement. Inspect parent and
child statuses and deliver the retained partial outputs if a child fails.
Use `child_options` only with options supported by the named child capability.

`music.separate` currently supports `stems=["vocals","instrumental"]` with
`profile=fast|balanced|quality`. Inspect future registry updates before asking
for other stem combinations. Pass only capability options, never shell arguments.

A stem is audio. A track is a group of symbolic note events. Resolve artifact
references before passing a stem to another capability. Preserve each child
result when combining analysis, separation and transcription. Do not merge
competing transcriptions into an asserted accurate score.

Present audio with a player and link the MIDI. For multitrack output, show the
instrument names and note timelines from that result. MuScriptor MIDI preserves
event timing without score quantization. Fingerprint comparison uses aligned
recording prefixes, not style similarity. Latency and quality depend on the
recording; model predictions are not reference annotations.

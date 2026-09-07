"""Create compact slide audio derivatives and waveform posters from real outputs."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'output/demo/slides/build/media'
SOURCES = {
    'original': ROOT / 'output/demo/music-singing/source.ogg',
    'vocals': ROOT / 'output/demo/music-singing/stem-vocals.wav',
    'instrumental': ROOT / 'output/demo/music-singing/stem-instrumental.wav',
    'generated': ROOT / 'output/demo/music-singing/generated.wav',
    'noisy': ROOT / 'docs/assets/e2e/meeting-two-speaker-noisy.wav',
    'denoised': ROOT / 'output/demo/core15-20260907/assets/audio-denoised-balanced.wav',
}


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    records = []
    for name, source in SOURCES.items():
        audio, poster = OUTPUT / f'{name}.mp3', OUTPUT / f'{name}.png'
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', str(source),
            '-map', '0:a:0', '-c:a', 'libmp3lame', '-b:a', '192k', str(audio)], check=True)
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', str(audio),
            '-filter_complex', 'aformat=channel_layouts=mono,showwavespic=s=640x120:colors=0x28624A',
            '-frames:v', '1', str(poster)], check=True)
        records.append({'id': name, 'audio': str(audio), 'poster': str(poster),
            'source': str(source), 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
            'sha256': hashlib.sha256(audio.read_bytes()).hexdigest(), 'encoding': 'MP3 192kbps'})
    (OUTPUT / 'manifest.json').write_text(json.dumps(records, indent=2) + '\n')


if __name__ == '__main__':
    main()

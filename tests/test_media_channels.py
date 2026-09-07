import shutil
import wave

import pytest

from specialist.media import audio_transform


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='FFmpeg required')
def test_resample_changes_rate_and_channels(tmp_path):
    source = tmp_path / 'stereo.wav'
    with wave.open(str(source), 'wb') as audio:
        audio.setnchannels(2)
        audio.setsampwidth(2)
        audio.setframerate(48000)
        audio.writeframes(b'\0' * 48000 * 4)
    result = audio_transform(source, tmp_path / 'out', 'resample', sample_rate=16000, channels=1)
    with wave.open(result['audio_path'], 'rb') as audio:
        assert audio.getnchannels() == 1
        assert audio.getframerate() == 16000
        assert audio.getnframes() == 16000

"""Validation tests for retained CLI evidence, independent of model inference."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('cached,status,expected', [(False, 'ok', 0), (True, 'ok', 1), (False, 'degraded', 1)])
def test_capture_rejects_cached_and_degraded(tmp_path, cached, status, expected):
    envelope = {'error': None, 'performance': {'cached': cached}, 'result': {'status': status}}
    output = tmp_path / 'capture'
    run = subprocess.run([sys.executable, str(ROOT / 'scripts/capture_demo_step.py'),
                          '--output', str(output), '--', sys.executable, '-c',
                          'print(' + repr(json.dumps(envelope)) + ')'], capture_output=True, text=True)
    assert run.returncode == expected
    assert json.loads((output / 'result.json').read_text()) == envelope
    assert json.loads((output / 'summary.json').read_text())['passed'] is (expected == 0)


def test_capture_retains_invalid_output(tmp_path):
    output = tmp_path / 'capture'
    run = subprocess.run([sys.executable, str(ROOT / 'scripts/capture_demo_step.py'),
                          '--output', str(output), '--', sys.executable, '-c',
                          'print("not an envelope")'], capture_output=True, text=True)
    assert run.returncode == 1
    assert (output / 'result.json').read_text() == 'not an envelope\n'
    assert json.loads((output / 'summary.json').read_text())['error']['code'] == 'invalid_cli_output'

"""Run a real CLI step and retain full output without flooding the presentation."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command:
        parser.error('A command is required after --')
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'command.json').write_text(json.dumps(command, indent=2))
    started = time.perf_counter()
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, start_new_session=os.name == 'posix')
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=900)
    except subprocess.TimeoutExpired:
        timed_out = True
        if os.name == 'posix':
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        stdout, stderr = process.communicate()
    (args.output / 'result.json').write_text(stdout)
    (args.output / 'stderr.log').write_text(stderr)
    try:
        value = json.loads(stdout)
        if not isinstance(value, dict):
            raise ValueError('Expected an object envelope')
    except ValueError:
        value = {'error': {'code': 'invalid_cli_output', 'message': 'Inspect result.json and stderr.log'}}
    if timed_out:
        value['error'] = {'code': 'provider_timeout', 'message': 'CLI exceeded 900 seconds'}
    passed = process.returncode == 0 and not value.get('error') and value.get('performance', {}).get('cached') is False and (value.get('result') or {}).get('status') != 'degraded'
    summary = {'passed': passed, 'capability': value.get('capability'), 'provider': value.get('provider'),
        'performance': value.get('performance'), 'wall_seconds': round(time.perf_counter() - started, 3),
        'error': value.get('error'), 'output': str(args.output.resolve())}
    (args.output / 'summary.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())

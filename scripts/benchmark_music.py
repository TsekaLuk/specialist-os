#!/usr/bin/env python3
"""Prepare licensed recordings and run real isolated CLI regression benchmarks.

Preparation requires FFmpeg and libarchive-c (for streaming one GuitarSet file).
Provider environments and model weights are installed through Specialist OS.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from specialist.cache import Cache
from specialist.models import ModelManager
from specialist.registry import get_spec
from specialist.schemas import validate_envelope


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def prepare(manifest, output, cache):
    sources = output / 'sources'
    sources.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, source in manifest['sources'].items():
        path = sources / (source.get('member') or name)
        if not path.is_file() or digest(path) != source['sha256']:
            if source.get('member'):
                import libarchive
                # Stop after the verified member; do not fetch 650 MB of unrelated recordings.
                temporary = path.with_suffix('.partial')
                with urllib.request.urlopen(source['url'], timeout=60) as response:
                    with libarchive.stream_reader(response) as archive:
                        for entry in archive:
                            if entry.pathname == source['member']:
                                with temporary.open('wb') as stream:
                                    for block in entry.get_blocks():
                                        stream.write(block)
                                break
                if not temporary.exists() or digest(temporary) != source['sha256']:
                    raise ValueError('GuitarSet member hash mismatch')
                temporary.replace(path)
            else:
                ModelManager(cache).download(source['url'], path, source['sha256'])
        paths[name] = path
    fixtures = []
    for fixture in manifest['fixtures']:
        original = paths[fixture['source']]
        if fixture.get('member'):
            extracted = sources / Path(fixture['member']).name
            with zipfile.ZipFile(original) as archive:
                extracted.write_bytes(archive.read(fixture['member']))
            original = extracted
        destination = output / (fixture['category'] + '.wav')
        command = ['ffmpeg', '-nostdin', '-v', 'error', '-y', '-ss', str(fixture.get('start', 0)),
                   '-i', str(original), '-map', f"0:a:{fixture.get('stream', 0)}", '-t', str(fixture['duration']),
                   '-ar', '8000' if fixture.get('degradation') else '44100',
                   '-ac', '1' if fixture.get('degradation') else '2', '-c:a', 'pcm_s16le', str(destination)]
        subprocess.run(command, check=True, timeout=60)
        fixtures.append({**fixture, 'path': str(destination.resolve()), 'sha256': digest(destination),
                         'preparation_command': command, 'source_metadata': manifest['sources'][fixture['source']]})
    return fixtures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=ROOT / 'tests/fixtures/music/benchmark.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'output/music-benchmark')
    parser.add_argument('--home', type=Path, required=True)
    parser.add_argument('--python', default=sys.executable)
    parser.add_argument('--capability', action='append')
    parser.add_argument('--only', action='append', help='Run selected fixture categories')
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    args.output.mkdir(parents=True, exist_ok=True)
    fixtures = prepare(manifest, args.output, Cache(args.home))
    report = {'fixtures': fixtures, 'records': [], 'accuracy': None,
              'artifact_home': str(args.home.resolve()),
              'accuracy_reason': 'Reference note/beat annotations are not part of this fixture set.'}
    capabilities = args.capability or ['music.analyze', 'music.fingerprint', 'music.transcribe_notes']
    report_path = args.output / 'report.json'
    if report_path.exists():
        previous = json.loads(report_path.read_text())
        if {f['category']: f['sha256'] for f in previous['fixtures']} != {f['category']: f['sha256'] for f in fixtures}:
            raise ValueError('Use a new output directory when fixture identities change')
        if previous.get('artifact_home', str(args.home.resolve())) != str(args.home.resolve()):
            raise ValueError('Cannot combine benchmark runs from different artifact homes')
        report['records'] = [row for row in previous['records'] if not
            (row['capability'] in capabilities and (not args.only or row['category'] in args.only))]
    for fixture in fixtures:
        if args.only and fixture['category'] not in args.only:
            continue
        for capability in capabilities:
            command = [str(Path(args.python).absolute()), '-m', 'specialist', '--home', str(args.home.resolve()),
                       '--backend', 'real', '--isolate', get_spec(capability).command, fixture['path'],
                       '--json', '--options', json.dumps({'no_cache': True, 'local_only': True})]
            run = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=960)
            value = json.loads(run.stdout)
            validate_envelope(value)
            passed = run.returncode == 0 and value['error'] is None and not value['performance']['cached']
            if value['input']['sha256'] != fixture['sha256']:
                raise ValueError('Benchmark input identity mismatch')
            result = f"{fixture['category']}-{capability}.json"
            (args.output / result).write_text(json.dumps(value, indent=2) + '\n')
            report['records'].append({'category': fixture['category'], 'capability': capability,
                'status': 'ok' if passed else 'error', 'command': command, 'result': result,
                'latency_ms': value['performance']['latency_ms'], 'error': value['error']})
            (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
            print(f"{fixture['category']} / {capability}: {'ok' if passed else 'error'}", flush=True)
    return int(any(row['status'] != 'ok' for row in report['records']))


if __name__ == '__main__':
    raise SystemExit(main())

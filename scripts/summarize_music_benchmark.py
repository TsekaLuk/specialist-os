"""Publish compact Music regression evidence without machine-specific paths."""
import argparse
import hashlib
import json
from pathlib import Path


def summarize(report_path):
    report = json.loads(report_path.read_text())
    records = []
    for row in report['records']:
        raw = (report_path.parent / row['result']).read_bytes()
        result = json.loads(raw)
        if row['status'] != 'ok' or result['error'] or result['performance']['cached']:
            raise ValueError('Only successful uncached records can enter the release summary')
        records.append({'category': row['category'], 'capability': row['capability'],
            'provider': result['provider'], 'model': result['model'], 'input_sha256': result['input']['sha256'],
            'result_sha256': hashlib.sha256(raw).hexdigest(), 'performance': result['performance']})
    return {'schema_version': 1, 'fixture_manifest': 'tests/fixtures/music/benchmark.json',
        'reproduce': 'scripts/benchmark_music.py', 'records': records,
        'accuracy': report['accuracy'], 'accuracy_reason': report['accuracy_reason']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.write_text(json.dumps(summarize(args.report), indent=2) + '\n')

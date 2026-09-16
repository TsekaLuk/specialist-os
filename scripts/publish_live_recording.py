"""Publish selected fresh CLI results into a separate recorded-demo workspace."""
import argparse
import json
import mimetypes
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from specialist.artifacts import ArtifactStore
from generate_readme_gallery import _annotated_image
from build_demo_site import replay_command
from publish_workspace import publish


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--result', action='append', type=Path, default=[])
    parser.add_argument('--batch', type=Path)
    parser.add_argument('--home', type=Path, default=Path.home() / '.specialist')
    args = parser.parse_args()
    site = ROOT / 'output/demo/live-workspace'
    if not site.exists():
        shutil.copytree(ROOT / 'output/demo/core15-20260907', site)
    manifest = json.loads((site / 'demo.json').read_text())
    values = [json.loads(path.read_text()) for path in args.result]
    if args.batch:
        values.extend(json.loads(args.batch.read_text())['results'])
    store = ArtifactStore(args.home / 'artifacts')
    assets = site / 'assets'
    for value in values:
        if value.get('error') or value['performance']['cached'] or value['result'].get('status') == 'degraded':
            raise ValueError('Only fresh successful results can replace recording evidence')
        item = next(entry for entry in manifest['results'] if entry['capability'] == value['capability'])
        (assets / item['json']).write_text(json.dumps(value, indent=2))
        source = Path(value['input']['path'])
        if source.is_file():
            shutil.copyfile(source, assets / source.name)
        item.update(cached=False, status='ok', latency_ms=value['performance']['latency_ms'],
            command=replay_command(value), command_origin='reconstructed', preview_unavailable=False)
        if value['capability'] in {'vision.detect', 'vision.segment'}:
            filename = value['capability'].replace('.', '-') + '-live.png'
            _annotated_image(source, value['result'], 'detect' if value['capability'] == 'vision.detect' else 'sam').save(assets / filename)
            item['preview'] = filename
        for ref in value.get('artifacts', []):
            suffix = mimetypes.guess_extension(ref['mime']) or '.bin'
            filename = ref['sha256'] + suffix
            shutil.copyfile(store.resolve(ref), assets / filename)
            if value['result'].get('preview') == ref['uri']:
                item['preview'] = filename
    (site / 'demo.json').write_text(json.dumps(manifest, indent=2))
    publish(ROOT / 'frontend/dist', site)
    print('http://127.0.0.1:8744/live-workspace/index.html')


if __name__ == '__main__':
    main()

"""Verify packaged audio bytes, relationships, click timing and full decoding."""
import argparse
import hashlib
import json
import posixpath
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET
import zipfile

from embed_slide_audio import NS


def check(deck, manifest):
    expected = {item['id']: item['sha256'] for item in json.loads(manifest.read_text())}
    found = {}
    with zipfile.ZipFile(deck) as archive:
        for name in archive.namelist():
            if not name.startswith('ppt/slides/slide') or not name.endswith('.xml'):
                continue
            slide = ET.fromstring(archive.read(name))
            players = slide.findall('.//a:audioFile', NS)
            if not players:
                continue
            relationships = ET.fromstring(archive.read(str(Path(name).parent / '_rels' / (Path(name).name + '.rels'))))
            rels = {rel.get('Id'): rel for rel in relationships}
            for pic in slide.findall('.//p:pic', NS):
                audio = pic.find('p:nvPicPr/p:nvPr/a:audioFile', NS)
                if audio is None:
                    continue
                props = pic.find('p:nvPicPr/p:cNvPr', NS)
                key = props.get('descr').removeprefix('audio:')
                rel = rels[audio.get('{' + NS['r'] + '}link')]
                assert rel.get('TargetMode') != 'External'
                target = posixpath.normpath(posixpath.join('ppt/slides', rel.get('Target')))
                data = archive.read(target)
                assert hashlib.sha256(data).hexdigest() == expected[key]
                assert props.find('a:hlinkClick', NS).get('action') == 'ppaction://media'
                timers = slide.findall('.//p:audio/p:cMediaNode', NS)
                timer = next(t for t in timers if t.find('p:tgtEl/p:spTgt', NS).get('spid') == props.get('id'))
                assert timer.find('p:cTn/p:stCondLst/p:cond', NS).get('delay') == 'indefinite'
                subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', 'pipe:0', '-f', 'null', '-'],
                               input=data, capture_output=True, check=True, timeout=60)
                found[key] = {'slide': name, 'bytes': len(data), 'sha256': expected[key], 'decoded': True}
    assert set(found) == set(expected)
    return {'passed': True, 'media': found}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('deck', type=Path)
    parser.add_argument('manifest', type=Path)
    args = parser.parse_args()
    print(json.dumps(check(args.deck, args.manifest), indent=2))

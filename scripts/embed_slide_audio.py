"""Add native embedded OOXML audio to existing waveform pictures in a draft PPTX.

The presentation tool owns layout. This packaging step adds media relationships
and click-to-play timing, retaining every other presentation part unchanged.
"""
import argparse
import hashlib
import json
from pathlib import Path
import posixpath
import xml.etree.ElementTree as ET
import zipfile

NS = {'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
      'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
      'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
      'p14': 'http://schemas.microsoft.com/office/powerpoint/2010/main',
      'rel': 'http://schemas.openxmlformats.org/package/2006/relationships',
      'ct': 'http://schemas.openxmlformats.org/package/2006/content-types'}
for prefix, uri in NS.items():
    ET.register_namespace(prefix, uri)


def add(parent, name, attributes=None):
    prefix, local = name.split(':')
    return ET.SubElement(parent, '{' + NS[prefix] + '}' + local, attributes or {})


def embed(source, destination, manifest):
    if source.resolve() == destination.resolve():
        raise ValueError('Write media to a new draft, not over the source')
    with zipfile.ZipFile(source) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    media = {item['id']: item for item in json.loads(manifest.read_text())}
    posters = {hashlib.sha256(Path(item['poster']).read_bytes()).hexdigest(): key for key, item in media.items()}
    embedded = []
    for name in list(parts):
        if not name.startswith('ppt/slides/slide') or not name.endswith('.xml'):
            continue
        slide = ET.fromstring(parts[name])
        rel_name = str(Path(name).parent / '_rels' / (Path(name).name + '.rels'))
        rels = ET.fromstring(parts[rel_name])
        targets = {rel.get('Id'): rel.get('Target') for rel in rels}
        pictures = []
        for pic in slide.findall('.//p:pic', NS):
            props = pic.find('p:nvPicPr/p:cNvPr', NS)
            blip = pic.find('p:blipFill/a:blip', NS)
            if props is None or blip is None:
                continue
            target = targets.get(blip.get('{' + NS['r'] + '}embed'))
            if not target:
                continue
            part = posixpath.normpath(posixpath.join('ppt/slides', target)) if not target.startswith('/') else target[1:]
            key = posters.get(hashlib.sha256(parts[part]).hexdigest())
            if key:
                props.set('descr', 'audio:' + key)
                props.set('name', key)
                pictures.append((pic, props))
        if not pictures:
            continue
        timing = slide.find('p:timing', NS)
        if timing is not None:
            raise ValueError('Audio injection requires slides without existing timing')
        timing = ET.Element('{' + NS['p'] + '}timing')
        ext = slide.find('p:extLst', NS)
        slide.insert(list(slide).index(ext) if ext is not None else len(slide), timing)
        root = add(add(add(timing, 'p:tnLst'), 'p:par'), 'p:cTn',
                   {'id': '1', 'dur': 'indefinite', 'restart': 'never', 'nodeType': 'tmRoot'})
        children = add(root, 'p:childTnLst')
        for index, (picture, props) in enumerate(pictures, 2):
            key = props.get('descr')[6:]
            item = media[key]
            payload = Path(item['audio']).read_bytes()
            if hashlib.sha256(payload).hexdigest() != item['sha256']:
                raise ValueError('Audio derivative checksum mismatch')
            target = f'../media/specialist-{key}.mp3'
            parts[f'ppt/media/specialist-{key}.mp3'] = payload
            audio_id, media_id = f'rIdSpecialistAudio{index}', f'rIdSpecialistMedia{index}'
            existing_ids = {rel.get('Id') for rel in rels}
            if audio_id in existing_ids or media_id in existing_ids:
                raise ValueError('Audio relationship id collision')
            add(rels, 'rel:Relationship', {'Id': audio_id, 'Type': NS['r'] + '/audio', 'Target': target})
            add(rels, 'rel:Relationship', {'Id': media_id, 'Type': 'http://schemas.microsoft.com/office/2007/relationships/media', 'Target': target})
            add(props, 'a:hlinkClick', {'action': 'ppaction://media'})
            nv = picture.find('p:nvPicPr/p:nvPr', NS)
            add(nv, 'a:audioFile', {'{' + NS['r'] + '}link': audio_id})
            extension = add(add(nv, 'p:extLst'), 'p:ext', {'uri': '{DAA4B4D4-6D71-4841-9C94-3DE7FCFB9230}'})
            add(extension, 'p14:media', {'{' + NS['r'] + '}embed': media_id})
            node = add(add(children, 'p:audio'), 'p:cMediaNode', {'vol': '100000'})
            ctn = add(node, 'p:cTn', {'id': str(index), 'fill': 'hold', 'display': '0'})
            add(add(ctn, 'p:stCondLst'), 'p:cond', {'delay': 'indefinite'})
            add(add(node, 'p:tgtEl'), 'p:spTgt', {'spid': props.get('id')})
            embedded.append({'slide': name, 'id': key, 'sha256': item['sha256']})
        parts[name] = ET.tostring(slide, encoding='utf-8', xml_declaration=True)
        parts[rel_name] = ET.tostring(rels, encoding='utf-8', xml_declaration=True)
    if len(embedded) != len(media):
        raise ValueError('Every requested audio must have exactly one slide player')
    types = ET.fromstring(parts['[Content_Types].xml'])
    if not any(item.get('Extension') == 'mp3' for item in types):
        add(types, 'ct:Default', {'Extension': 'mp3', 'ContentType': 'audio/mpeg'})
    ET.register_namespace('', NS['ct'])
    parts['[Content_Types].xml'] = ET.tostring(types, encoding='utf-8', xml_declaration=True)
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    print(json.dumps({'embedded': embedded}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    parser.add_argument('manifest', type=Path)
    args = parser.parse_args()
    embed(args.source, args.destination, args.manifest)

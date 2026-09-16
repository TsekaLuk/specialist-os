"""Append one authored media slide, preserving the source deck's existing parts."""
import argparse
from pathlib import Path
import posixpath
import xml.etree.ElementTree as ET
import zipfile

NS = {'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
      'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
      'rel': 'http://schemas.openxmlformats.org/package/2006/relationships',
      'ct': 'http://schemas.openxmlformats.org/package/2006/content-types'}


def append(source, addition, destination):
    if destination.exists():
        raise ValueError('Destination already exists')
    with zipfile.ZipFile(source) as z:
        parts = {name: z.read(name) for name in z.namelist()}
    with zipfile.ZipFile(addition) as z:
        extra = {name: z.read(name) for name in z.namelist()}
    pres = ET.fromstring(parts['ppt/presentation.xml'])
    ids = pres.find('p:sldIdLst', NS)
    number = len(ids) + 1
    slide_name = f'ppt/slides/slide{number}.xml'
    rel_name = f'ppt/slides/_rels/slide{number}.xml.rels'
    rels = ET.fromstring(extra['ppt/slides/_rels/slide1.xml.rels'])
    previous = ET.fromstring(parts[f'ppt/slides/_rels/slide{number-1}.xml.rels'])
    layout = next(rel.get('Target') for rel in previous if rel.get('Type').endswith('/slideLayout'))
    for rel in list(rels):
        kind = rel.get('Type').rsplit('/', 1)[-1]
        if kind == 'slideLayout':
            rel.set('Target', layout)
        elif kind == 'notesSlide':
            rels.remove(rel)
        elif rel.get('TargetMode') != 'External':
            target = rel.get('Target')
            original = posixpath.normpath(posixpath.join('ppt/slides', target)) if not target.startswith('/') else target[1:]
            name = 'ppt/media/video-demo-' + Path(original).name
            if name in parts and parts[name] != extra[original]:
                raise ValueError('Media part collision')
            parts[name] = extra[original]
            rel.set('Target', '../media/' + Path(name).name)
    parts[slide_name] = extra['ppt/slides/slide1.xml']
    parts[rel_name] = ET.tostring(rels, encoding='utf-8', xml_declaration=True)
    pres_rels = ET.fromstring(parts['ppt/_rels/presentation.xml.rels'])
    rid = 'rIdSpecialistDemoVideo'
    ET.SubElement(pres_rels, '{'+NS['rel']+'}Relationship', {'Id': rid, 'Type': NS['r']+'/slide', 'Target':f'slides/slide{number}.xml'})
    ET.SubElement(ids, '{'+NS['p']+'}sldId', {'id': str(max(int(item.get('id')) for item in ids)+1), '{'+NS['r']+'}id':rid})
    parts['ppt/presentation.xml'] = ET.tostring(pres, encoding='utf-8', xml_declaration=True)
    parts['ppt/_rels/presentation.xml.rels'] = ET.tostring(pres_rels, encoding='utf-8', xml_declaration=True)
    types = ET.fromstring(parts['[Content_Types].xml'])
    ET.SubElement(types, '{'+NS['ct']+'}Override', {'PartName':'/'+slide_name,'ContentType':'application/vnd.openxmlformats-officedocument.presentationml.slide+xml'})
    for item in ET.fromstring(extra['[Content_Types].xml']):
        if item.tag.endswith('Default') and not any(node.get('Extension') == item.get('Extension') for node in types):
            types.append(item)
    ET.register_namespace('', NS['ct'])
    parts['[Content_Types].xml'] = ET.tostring(types, encoding='utf-8', xml_declaration=True)
    with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED) as z:
        for name, payload in parts.items():
            z.writestr(name,payload)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('addition', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    append(args.source,args.addition,args.destination)

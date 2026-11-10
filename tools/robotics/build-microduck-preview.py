#!/usr/bin/env python3
"""Build a display-only GLB from pinned Microduck visual meshes. No physics export.

Uses standard-library Python only. Preserves MJCF body/geom transforms and colors;
excludes collision geoms, inertias, sensors and actuators. GLTF is Y-up, so the
root rotates the Z-up MJCF model; the Studio viewer reverses that rotation.
"""
import gzip
import hashlib
import json
import math
from pathlib import Path
import struct
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'packages/models/microduck/0.1.0'


def build(destination: Path):
    manifest_raw = (SOURCE / 'manifest.json').read_bytes()
    manifest = json.loads(manifest_raw)
    files = {}
    for entry in manifest['files']:
        raw = (SOURCE / entry['path']).read_bytes()
        if len(raw) != entry['size_bytes'] or hashlib.sha256(raw).hexdigest() != entry['sha256']:
            raise ValueError(f"Microduck source pin mismatch: {entry['path']}")
        files[entry['path']] = raw
    xml = ET.fromstring(files['robot_walk.xml'])
    gltf = {'asset': {'version': '2.0', 'generator': 'SeedCore Microduck visual-only exporter',
                      'copyright': 'Pollen Robotics · Apache-2.0'},
            'scene': 0, 'scenes': [{'nodes': [0]}], 'nodes': [], 'meshes': [],
            'materials': [], 'accessors': [], 'bufferViews': [], 'buffers': []}
    binary = bytearray()

    def accessor(values, kind, count, minimum=None, maximum=None, component=5126):
        while len(binary) % 4:
            binary.append(0)
        view = len(gltf['bufferViews'])
        gltf['bufferViews'].append({'buffer': 0, 'byteOffset': len(binary), 'byteLength': len(values)})
        binary.extend(values)
        entry = {'bufferView': view, 'componentType': component, 'count': count, 'type': kind}
        if minimum is not None:
            entry.update(min=minimum, max=maximum)
        gltf['accessors'].append(entry)
        return len(gltf['accessors']) - 1

    materials = {}
    for material in xml.findall('./asset/material'):
        materials[material.attrib['name']] = len(gltf['materials'])
        gltf['materials'].append({'name': material.attrib['name'], 'doubleSided': True,
                                 'pbrMetallicRoughness': {'baseColorFactor': list(map(float, material.attrib['rgba'].split())),
                                                          'metallicFactor': 0, 'roughnessFactor': 0.65}})
    geometry = {}
    for mesh in xml.findall('./asset/mesh'):
        filename = mesh.attrib['file']
        raw = files['assets/' + filename]
        count = struct.unpack_from('<I', raw, 80)[0]
        if len(raw) != 84 + count * 50:
            raise ValueError('Only pinned binary STL is supported')
        positions, normals, indices = bytearray(), bytearray(), bytearray()
        unique = {}
        lower, upper = [math.inf] * 3, [-math.inf] * 3
        for index in range(count):
            offset = 84 + index * 50
            normal = raw[offset:offset + 12]
            for vertex in range(3):
                data = raw[offset + 12 + vertex * 12:offset + 24 + vertex * 12]
                key = data + normal
                if key not in unique:
                    unique[key] = len(unique)
                    positions.extend(data)
                    normals.extend(normal)
                indices.extend(struct.pack('<I', unique[key]))
                for axis, value in enumerate(struct.unpack('<3f', data)):
                    lower[axis] = min(lower[axis], value)
                    upper[axis] = max(upper[axis], value)
        if len(positions) + len(normals) + len(indices) < count * 3 * 24:
            geometry[Path(filename).stem] = {
                'attributes': {'POSITION': accessor(positions, 'VEC3', len(unique), lower, upper),
                               'NORMAL': accessor(normals, 'VEC3', len(unique))},
                'indices': accessor(indices, 'SCALAR', count * 3, component=5125)}
        else:
            positions, normals = bytearray(), bytearray()
            for index in range(count):
                offset = 84 + index * 50
                positions.extend(raw[offset + 12:offset + 48])
                normals.extend(raw[offset:offset + 12] * 3)
            geometry[Path(filename).stem] = {'attributes': {
                'POSITION': accessor(positions, 'VEC3', count * 3, lower, upper),
                'NORMAL': accessor(normals, 'VEC3', count * 3)}}
    # A conforming Y-up glTF asset, with meters unchanged.
    half = math.sqrt(0.5)
    gltf['nodes'].append({'name': 'Microduck', 'rotation': [-half, 0, 0, half], 'children': []})
    mesh_cache = {}
    joints = []

    def transform(element):
        w, x, y, z = map(float, element.attrib.get('quat', '1 0 0 0').split())
        norm = math.sqrt(w*w + x*x + y*y + z*z)
        return {'translation': list(map(float, element.attrib.get('pos', '0 0 0').split())),
                'rotation': [x/norm, y/norm, z/norm, w/norm]}

    def body(element, parent):
        index = len(gltf['nodes'])
        node = {'name': element.attrib['name'], **transform(element), 'children': []}
        gltf['nodes'].append(node)
        gltf['nodes'][parent]['children'].append(index)
        joint = element.find('joint')
        if joint is not None:
            data = {'name': joint.attrib['name'], 'axis': list(map(float, joint.attrib['axis'].split())),
                    'range': list(map(float, joint.attrib['range'].split()))}
            node['extras'] = {'joint': data}
            joints.append(data)
        for geom in element.findall('geom'):
            if geom.attrib.get('class') != 'visual':
                continue
            key = (geom.attrib['mesh'], geom.attrib['material'])
            if key not in mesh_cache:
                mesh_cache[key] = len(gltf['meshes'])
                gltf['meshes'].append({'name': key[0], 'primitives': [
                    {**geometry[key[0]], 'material': materials[key[1]]}]})
            child = len(gltf['nodes'])
            gltf['nodes'].append({'name': geom.attrib['mesh'], **transform(geom), 'mesh': mesh_cache[key]})
            node['children'].append(child)
        for child in element.findall('body'):
            body(child, index)
    for element in xml.findall('./worldbody/body'):
        body(element, 0)
    gltf['buffers'] = [{'byteLength': len(binary)}]
    payload = json.dumps(gltf, separators=(',', ':'), ensure_ascii=True).encode()
    payload += b' ' * (-len(payload) % 4)
    binary += b'\0' * (-len(binary) % 4)
    glb = (struct.pack('<III', 0x46546C67, 2, 12 + 8 + len(payload) + 8 + len(binary))
           + struct.pack('<II', len(payload), 0x4E4F534A) + payload
           + struct.pack('<II', len(binary), 0x004E4942) + binary)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / 'microduck.glb').write_bytes(glb)
    (destination / 'microduck.glb.gz').write_bytes(gzip.compress(glb, compresslevel=6, mtime=0))
    (destination / 'microduck-preview.json').write_text(json.dumps({
        'schema': 'seedcore.visual-demo.v1', 'name': 'Microduck', 'scope': 'display_only',
        'physicalAcceptance': False, 'executionAuthority': 'none',
        'source': manifest['source'], 'sourceManifestSha256': hashlib.sha256(manifest_raw).hexdigest(),
        'asset': {'uri': 'microduck.glb', 'sha256': hashlib.sha256(glb).hexdigest(), 'bytes': len(glb)},
        'meshCount': len(geometry), 'bodyCount': len(xml.findall('.//worldbody//body')),
        'visualCount': sum(1 for g in xml.findall('.//worldbody//geom') if g.attrib.get('class') == 'visual'),
        'joints': joints,
    }, indent=2) + '\n')
    (destination / 'microduck-LICENSE.txt').write_bytes(files['LICENSE'])


if __name__ == '__main__':
    build(Path(sys.argv[1]))

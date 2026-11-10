"""The visual demo keeps the source body frames without becoming a physics model."""
import importlib.util
import json
from pathlib import Path
import struct
import xml.etree.ElementTree as ET

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_visual_export_matches_source_and_native_body_frames(tmp_path):
    spec = importlib.util.spec_from_file_location('preview_export', ROOT / 'tools/robotics/build-microduck-preview.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.build(tmp_path)
    raw = (tmp_path / 'microduck.glb').read_bytes()
    magic, version, length = struct.unpack_from('<III', raw)
    assert (magic, version, length) == (0x46546C67, 2, len(raw))
    json_length = struct.unpack_from('<I', raw, 12)[0]
    gltf = json.loads(raw[20:20 + json_length])
    metadata = json.loads((tmp_path / 'microduck-preview.json').read_text())
    assert metadata['scope'] == 'display_only'
    assert metadata['physicalAcceptance'] is False and metadata['executionAuthority'] == 'none'
    assert metadata['meshCount'] == 38 and metadata['bodyCount'] == 15
    assert len(metadata['joints']) == 14
    assert sum('mesh' in node for node in gltf['nodes']) == metadata['visualCount'] == 70
    source = ET.parse(module.SOURCE / 'robot_walk.xml')
    bodies = {element.attrib['name']: element for element in source.findall('.//worldbody//body')}
    nodes = {node['name']: node for node in gltf['nodes'] if 'children' in node and node['name'] in bodies}
    # Body and visual nodes can share names; only bodies have children arrays.
    assert set(nodes) == set(bodies)
    for name, element in bodies.items():
        assert nodes[name]['translation'] == list(map(float, element.attrib['pos'].split()))
    assert 'actuator' not in gltf and 'sensor' not in gltf

    mj = pytest.importorskip('mujoco')
    model = mj.MjModel.from_xml_path(str(module.SOURCE / 'robot_walk.xml'))
    data = mj.MjData(model)
    mj.mj_forward(model, data)
    transforms = {}

    def visit(index, parent):
        node = gltf['nodes'][index]
        x, y, z, w = node.get('rotation', [0, 0, 0, 1])
        rotation = np.empty(9)
        mj.mju_quat2Mat(rotation, np.array([w, x, y, z]))
        transform = np.eye(4)
        transform[:3, :3] = rotation.reshape(3, 3)
        transform[:3, 3] = node.get('translation', [0, 0, 0])
        world = parent @ transform
        if 'children' in node and node['name'] in bodies:
            transforms[node['name']] = world
        for child in node.get('children', []):
            visit(child, world)
    # Viewer cancels the glTF root's Z-up -> Y-up conversion.
    for child in gltf['nodes'][0]['children']:
        visit(child, np.eye(4))
    for name, transform in transforms.items():
        index = mj.mj_name2id(model, mj.mjtObj.mjOBJ_BODY, name)
        np.testing.assert_allclose(transform[:3, 3], data.xpos[index], atol=1e-10)
        np.testing.assert_allclose(transform[:3, :3], data.xmat[index].reshape(3, 3), atol=1e-10)

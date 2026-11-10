"""Packet evidence binding, incomplete human records, and non-destructive preflight."""
import importlib.util
import json
from pathlib import Path
import socket

import pytest

spec = importlib.util.spec_from_file_location('maker_trial', Path(__file__).parents[1] / 'scripts/robotics/prepare_maker_trial.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


@pytest.fixture
def candidate(tmp_path, monkeypatch):
    root = tmp_path
    def write(name, value):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value if isinstance(value, str) else json.dumps(value))
    source = sorted(m.REQUIRED_INPUTS)
    for name in source:
        write(name, 'source')
    for name in m.REQUIRED_BUILD:
        write(name, 'build')
    browser_path = 'artifacts/robotics/cw-l01/browser-verification.json'
    write(browser_path, {'status': 'checks_passed', 'checks': ['passed'] * 7})
    report = {'review_id': 'CW-GAL-01-LOCAL', 'status': 'checks_passed', 'scope': 'offline_proxy_authoring',
              'physical_acceptance': False, 'execution_authority': 'none', 'browser_included': True,
              'browser_checks': 7, 'checks': [{'label': label, 'exit_code': 0} for label in sorted(m.REQUIRED_CHECKS)], 'source_revision': 'a' * 40,
              'inputs': [m.pin(root, n) for n in source], 'outputs': [m.pin(root, browser_path)],
              'build_outputs': [m.pin(root, n) for n in sorted(m.REQUIRED_BUILD)]}
    write(m.REPORT, report)
    extras = ['scripts/robotics/prepare_maker_trial.py', 'tests/test_maker_trial.py', 'tools/robotics/verify-cw-l02-trial.py',
              'docs/development/robotics/central_world_cw_l02_maker_lesson.md',
              'docs/development/robotics/central_world_cw_l03_alpha_review.md', 'deploy/local/README.md']
    for name in extras:
        write(name, 'trial input')
    monkeypatch.setattr(m, 'git', lambda root, *args: 'a' * 40 if args == ('rev-parse', 'HEAD') else ' M docs/lesson.md')
    return root, report, write


def ready():
    return {'status': 'ready', 'port': 8767, 'browserChannel': 'chrome'}


def test_packet_pins_candidate_and_preserves_pending_observation(candidate):
    root, _, _ = candidate
    out = root / 'artifacts/robotics/cw-l02-trials/first'
    manifest = m.prepare(root, out, ready())
    record = json.loads((out / 'observation.json').read_text())
    assert record['status'] == 'pending' and record['independentAdultMakerObserved'] is False
    assert all(value is None for value in record['observations'].values())
    assert record['supportOwner'] is None and record['rollbackOwner'] is None
    assert record['releaseDecision'] == manifest['releaseDecision'] == 'defer'
    assert record['candidateDigest'] == manifest['candidateDigest']
    for entry in manifest['files']:
        assert m.pin(out, entry['path'])['sha256'] == entry['sha256']
    assert (out / 'lesson.md').read_bytes() == (root / m.LESSON).read_bytes()
    assert 'not a standalone' in (out / 'README.md').read_text()


@pytest.mark.parametrize('kind', ['inputs', 'outputs', 'build_outputs'])
def test_changed_artifact_fails_without_creating_output(candidate, kind):
    root, report, _ = candidate
    (root / report[kind][0]['path']).write_text('changed')
    out = root / 'artifacts/robotics/cw-l02-trials/stale'
    with pytest.raises(ValueError, match='Stale'):
        m.prepare(root, out, ready())
    assert not out.exists()


def test_new_unreported_build_file_and_missing_build_are_refused(candidate):
    root, _, write = candidate
    write(m.BUILD + 'extra.js', 'unreported')
    with pytest.raises(ValueError, match='inventory'):
        m.checked_report(root)
    (root / (m.BUILD + 'extra.js')).unlink()
    (root / next(iter(m.REQUIRED_BUILD))).unlink()
    with pytest.raises(ValueError, match='Missing'):
        m.checked_report(root)


@pytest.mark.parametrize('field,value', [('source_revision', 'b' * 40), ('browser_included', False),
    ('status', 'checks_failed'), ('physical_acceptance', True), ('build_outputs', []), ('inputs', []), ('outputs', [])])
def test_incomplete_or_wrong_revision_evidence_is_refused(candidate, field, value):
    root, report, write = candidate
    report[field] = value
    write(m.REPORT, report)
    with pytest.raises(ValueError):
        m.checked_report(root)


@pytest.mark.parametrize('name', ['../outside', '/tmp/outside', 'a/../outside', 'a\\outside', './outside'])
def test_unsafe_artifact_paths_are_refused(candidate, name):
    root, _, _ = candidate
    with pytest.raises(ValueError):
        m.pin(root, name)


def test_symlink_artifacts_and_json_duplicates_are_refused(candidate):
    root, _, write = candidate
    (root / 'linked').symlink_to(root / m.REPORT)
    with pytest.raises(ValueError, match='Symlink'):
        m.pin(root, 'linked')
    write('duplicate.json', '{"status":1,"status":2}')
    with pytest.raises(ValueError, match='Duplicate'):
        m.read_json(root, 'duplicate.json')


def test_existing_or_outside_output_is_not_overwritten(candidate):
    root, _, _ = candidate
    out = root / 'artifacts/robotics/cw-l02-trials/existing'
    out.mkdir(parents=True)
    sentinel = out / 'observation.json'
    sentinel.write_text('human observations')
    with pytest.raises(ValueError, match='already exists'):
        m.prepare(root, out, ready())
    assert sentinel.read_text() == 'human observations'
    with pytest.raises(ValueError, match='new child'):
        m.prepare(root, root / 'docs/replaced', ready())
    outside = root / 'external'
    outside.mkdir()
    (out.parent / 'link').symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match='Symlink'):
        m.prepare(root, out.parent / 'link' / 'trial', ready())


def test_blocked_preflight_never_creates_packet(candidate):
    root, _, _ = candidate
    with pytest.raises(ValueError, match='blocked'):
        m.prepare(root, root / 'artifacts/robotics/cw-l02-trials/blocked', {'status': 'blocked'})


def test_preflight_reports_occupied_port_without_stopping_listener(candidate, monkeypatch):
    root, _, _ = candidate
    monkeypatch.setattr(m, 'command_check', lambda *a, **kw: True)
    monkeypatch.setattr(m.importlib.util, 'find_spec', lambda name: object())
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        port = listener.getsockname()[1]
        result = m.preflight(root, port)
        assert result['status'] == 'blocked'
        check = next(c for c in result['checks'] if c['name'] == 'Local port available')
        assert not check['ok'] and 'unrelated' in check['remedy']
        with socket.create_connection(('127.0.0.1', port), timeout=1):
            pass


def test_missing_dependencies_are_actionable(candidate, monkeypatch):
    root, _, _ = candidate
    monkeypatch.setattr(m, 'command_check', lambda *a, **kw: False)
    monkeypatch.setattr(m.importlib.util, 'find_spec', lambda name: None)
    result = m.preflight(root, 58765)
    assert result['status'] == 'blocked'
    assert all(c['remedy'] for c in result['checks'] if not c['ok'])


def test_verify_refuses_changed_checkout_and_forged_observation(candidate):
    root, report, _ = candidate
    out = root / 'artifacts/robotics/cw-l02-trials/verify'
    m.prepare(root, out, ready())
    assert m.verify_packet(root, out)['observationStatus'] == 'pending'
    observation = json.loads((out / 'observation.json').read_text())
    observation['status'] = 'recorded'
    (out / 'observation.json').write_text(json.dumps(observation))
    with pytest.raises(ValueError, match='required manual evidence'):
        m.verify_packet(root, out)
    observation['status'] = 'pending'
    observation['candidateDigest'] = 'wrong'
    (out / 'observation.json').write_text(json.dumps(observation))
    with pytest.raises(ValueError, match='binding'):
        m.verify_packet(root, out)
    (root / report['inputs'][0]['path']).write_text('new code')
    with pytest.raises(ValueError, match='Stale'):
        m.verify_packet(root, out)


def test_verify_refuses_changed_packet_payload(candidate):
    root, _, _ = candidate
    out = root / 'artifacts/robotics/cw-l02-trials/tampered'
    m.prepare(root, out, ready())
    (out / 'lesson.md').write_text('rewritten instructions')
    with pytest.raises(ValueError, match='immutable'):
        m.verify_packet(root, out)


@pytest.mark.parametrize('contents', ['null', '[]', '1', '[' * 2000 + '0' + ']' * 2000])
def test_nonobject_or_deep_reports_are_actionable(candidate, contents):
    root, _, write = candidate
    write(m.REPORT, contents)
    with pytest.raises(ValueError):
        m.checked_report(root)


def test_recent_owned_listener_stop_is_not_mistaken_for_occupied_port(candidate, monkeypatch):
    root, _, _ = candidate
    monkeypatch.setattr(m, 'command_check', lambda *a, **kw: True)
    monkeypatch.setattr(m.importlib.util, 'find_spec', lambda name: object())
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(('127.0.0.1', 0)); listener.listen()
        port = listener.getsockname()[1]
        client = socket.create_connection(('127.0.0.1', port), timeout=1)
        accepted, _ = listener.accept()
        accepted.sendall(b'x'); accepted.close()
        client.recv(1); client.close()
    result = m.preflight(root, port)
    assert next(c for c in result['checks'] if c['name'] == 'Local port available')['ok']
    assert result['status'] == 'ready'


def test_lesson_payload_is_the_participant_document(candidate):
    root, _, write = candidate
    write(m.LESSON, '# Participant lesson\nStart with Meet Microduck.\n')
    write('tools/robotics/verify-cw-l02-trial.py', '# verifier is not a lesson')
    out = root / 'artifacts/robotics/cw-l02-trials/lesson'
    m.prepare(root, out, ready())
    assert (out / 'lesson.md').read_text().startswith('# Participant lesson')


def test_large_model_has_a_bounded_exception_without_widening_other_files(candidate):
    root, _, write = candidate
    name = m.BUILD + 'microduck.glb'
    with (root / name).open('wb') as stream:
        stream.truncate(21 * 1024 * 1024)
    assert m.pin(root, name)['bytes'] == 21 * 1024 * 1024
    with (root / name).open('wb') as stream:
        stream.truncate(65 * 1024 * 1024)
    with pytest.raises(ValueError, match='64 MiB'):
        m.pin(root, name)
    write('oversized.bin', '')
    with (root / 'oversized.bin').open('wb') as stream:
        stream.truncate(21 * 1024 * 1024)
    with pytest.raises(ValueError, match='20 MiB'):
        m.pin(root, 'oversized.bin')


@pytest.mark.parametrize('label', sorted(m.REQUIRED_CHECKS))
def test_new_studio_flows_cannot_reuse_old_gallery_only_evidence(candidate, label):
    root, report, write = candidate
    report['checks'] = [c for c in report['checks'] if c['label'] != label]
    write(m.REPORT, report)
    with pytest.raises(ValueError, match='browser acceptance'):
        m.checked_report(root)

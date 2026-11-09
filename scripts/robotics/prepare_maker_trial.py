#!/usr/bin/env python3
"""Read-only startup checks and a source-bound local maker-trial packet."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import platform
import socket
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
REPORT = 'artifacts/robotics/cw-l01/verification.json'
BUILD = 'ts/apps/mini-studio/dist/'
REQUIRED_BUILD = {BUILD + n for n in ('index.html', 'app.js', 'app.css', 'cw-s02-worker.js', 'mujoco.wasm', 'third-party-notices.txt')}
MAX_JSON = 2 * 1024 * 1024


def local_file(root: Path, name: str) -> Path:
    if not isinstance(name, str):
        raise ValueError('Unsafe relative artifact path')
    rel = PurePosixPath(name)
    if not name or rel.is_absolute() or '\\' in name or any(p in ('', '.', '..') for p in name.split('/')):
        raise ValueError('Unsafe relative artifact path')
    path = root.joinpath(*rel.parts)
    if any(root.joinpath(*rel.parts[:i]).is_symlink() for i in range(1, len(rel.parts) + 1)):
        raise ValueError('Symlink artifact refused')
    if not path.is_file():
        raise ValueError(f'Missing file: {name}')
    return path


def read_json(root: Path, name: str):
    path = local_file(root, name)
    if path.stat().st_size > MAX_JSON:
        raise ValueError('JSON artifact exceeds 2 MiB')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    try:
        value = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))
    except RecursionError as error:
        raise ValueError('JSON nesting exceeds parser limits') from error
    if not isinstance(value, dict):
        raise ValueError('Expected a JSON object')
    return value


def pin(root: Path, name: str):
    path = local_file(root, name)
    if path.stat().st_size > 20 * 1024 * 1024:
        raise ValueError('Artifact exceeds 20 MiB')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(65536), b''):
            digest.update(block)
    return {'path': name, 'bytes': path.stat().st_size, 'sha256': digest.hexdigest()}


def git(root: Path, *args: str) -> str:
    result = subprocess.run(['git', *args], cwd=root, capture_output=True, text=True, timeout=10, check=True)
    return result.stdout.strip()


def checked_report(root: Path):
    report = read_json(root, REPORT)
    if (report.get('review_id') != 'CW-GAL-01-LOCAL' or report.get('status') != 'checks_passed'
        or report.get('scope') != 'offline_proxy_authoring' or report.get('physical_acceptance') is not False
        or report.get('execution_authority') != 'none' or report.get('browser_included') is not True
        or not isinstance(report.get('browser_checks'), int) or report['browser_checks'] < 7):
        raise ValueError('Source-built gallery/browser acceptance is missing or incomplete')
    if report.get('source_revision') != git(root, 'rev-parse', 'HEAD'):
        raise ValueError('Verification revision differs from HEAD; rerun the gallery gate')
    required_inputs = {'ts/apps/mini-studio/src/app.ts', 'ts/apps/mini-studio/src/gallery.ts',
                       'ts/apps/mini-studio/build.mjs', 'src/seedcore/robotics/mini_studio_api.py',
                       'tools/robotics/verify-cw-l01.cjs'}
    if not required_inputs.issubset({e.get('path') for e in report.get('inputs', [])}):
        raise ValueError('Incomplete source inventory')
    if 'artifacts/robotics/cw-l01/browser-verification.json' not in {e.get('path') for e in report.get('outputs', [])}:
        raise ValueError('Browser evidence is not pinned')
    for group in ('inputs', 'outputs', 'build_outputs'):
        entries = report.get(group)
        if not isinstance(entries, list) or not 1 <= len(entries) <= 2048:
            raise ValueError(f'Missing or oversized verification inventory: {group}')
        seen = set()
        for entry in entries:
            name = entry['path']
            if name in seen:
                raise ValueError('Duplicate artifact inventory entry')
            seen.add(name)
            if pin(root, name)['sha256'] != entry['sha256']:
                raise ValueError(f'Stale verification artifact: {name}')
        if group == 'build_outputs':
            actual = {p.relative_to(root).as_posix() for p in (root / BUILD).rglob('*') if p.is_file()}
            if not REQUIRED_BUILD.issubset(seen) or actual != seen:
                raise ValueError('Incomplete Studio build inventory')
    browser = read_json(root, 'artifacts/robotics/cw-l01/browser-verification.json')
    if browser.get('status') != 'checks_passed' or len(browser.get('checks', [])) < 7:
        raise ValueError('Missing gallery browser evidence')
    return report


def command_check(root: Path, command: list[str], timeout=15):
    try:
        result = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=timeout)
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def preflight(root: Path, port: int = 8767, channel: str = 'chrome'):
    if not 1 <= port <= 65535 or channel not in ('chrome', 'bundled'):
        raise ValueError('Invalid port or browser channel')
    checks = []
    def add(name, ok, remedy):
        checks.append({'name': name, 'ok': bool(ok), 'remedy': None if ok else remedy})
    add('Python >=3.12', sys.version_info >= (3, 12), 'Use the project Python 3.12+ virtual environment.')
    for module in ('fastapi', 'uvicorn', 'jsonschema', 'rfc8785', 'numpy'):
        add(f'Python module {module}', importlib.util.find_spec(module) is not None, f'Install the documented project dependencies in the chosen virtual environment; missing {module}.')
    add('Node', command_check(root, ['node', '--version']), 'Install Node and the TS workspace dependencies using the documented setup.')
    add('npm', command_check(root, ['npm', '--version']), 'Make npm available; install workspace dependencies with npm ci from ts/.')
    try:
        checked_report(root)
        add('Source-bound accepted Studio build', True, '')
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as error:
        add('Source-bound accepted Studio build', False, f'{error}. Run node tools/robotics/verify-cw-l01.cjs --browser.')
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(('127.0.0.1', port))
            probe.listen(1)
            available = True
        except OSError:
            available = False
    add('Local port available', available, f'Port {port} is unavailable. Choose another --port or stop only your own Studio with Ctrl-C; do not kill an unrelated service.')
    # Fixed local Playwright invocation. No browser installation, navigation or network access.
    js = "const p=require(require.resolve('playwright',{paths:[process.cwd()+'/ts/apps/mini-studio']}));(async()=>{const b=await p.chromium.launch({headless:true,timeout:10000,...(process.argv[1]==='bundled'?{}:{channel:'chrome'})});await b.close()})().catch(()=>process.exit(1));"
    add('Browser and Playwright', command_check(root, ['node', '-e', js, channel]), 'Install the documented Playwright dependency and selected Chrome/bundled Chromium, then rerun. Nothing is installed automatically.')
    return {'schemaVersion': 'seedcore.maker-preflight.v1', 'status': 'ready' if all(c['ok'] for c in checks) else 'blocked',
            'scope': 'local_simulation_trial_only', 'physicalAcceptance': False, 'executionAuthority': 'none',
            'port': port, 'browserChannel': channel, 'pythonVersion': platform.python_version(), 'checks': checks,
            'notes': ['Port availability is a point-in-time check; startup can still fail if another process claims it.',
                      'Native MuJoCo and Rust are needed for their separate verification lanes, not this browser-only lesson.']}


def observation_template(candidate_digest: str):
    fields = ('browser_device', 'setup_time_seconds', 'task_outcomes', 'task_time_seconds', 'assistance',
              'keyboard_accessibility', 'stop_recovery', 'privacy_egress', 'downloaded_artifact', 'reviewer_findings')
    return {'schemaVersion': 'seedcore.maker-observation.v1', 'candidateDigest': candidate_digest,
            'status': 'pending', 'independentAdultMakerObserved': False,
            'observations': {field: None for field in fields}, 'supportOwner': None, 'rollbackOwner': None,
            'releaseDecision': 'defer', 'instructions': 'Fill only from actual observation. Do not include names, credentials or private account data. This record cannot authorize execution or publication.'}


def prepare(root: Path, destination: Path, readiness: dict):
    if readiness.get('status') != 'ready':
        raise ValueError('Preflight is blocked; no trial packet created')
    report = checked_report(root)
    destination = destination.absolute()
    trial_root = root / 'artifacts/robotics/cw-l02-trials'
    if not destination.is_relative_to(trial_root) or '..' in destination.parts or destination == trial_root:
        raise ValueError('Output must be a new child of artifacts/robotics/cw-l02-trials/')
    # Refuse existing paths and symlink parents rather than overwrite any trial or source.
    for parent in [destination, *destination.parents]:
        if parent == root:
            break
        if parent.is_symlink():
            raise ValueError('Symlink output path refused')
    if destination.exists():
        raise ValueError('Output already exists; choose a new trial directory')
    extras = ['scripts/robotics/prepare_maker_trial.py', 'tests/test_maker_trial.py', 'tools/robotics/verify-cw-l02-trial.py',
              'docs/development/robotics/central_world_cw_l02_maker_lesson.md',
              'docs/development/robotics/central_world_cw_l03_alpha_review.md', 'deploy/local/README.md']
    candidate = {'schemaVersion': 'seedcore.maker-candidate.v1', 'revision': git(root, 'rev-parse', 'HEAD'),
                 'workingTreeStatus': git(root, 'status', '--porcelain'), 'scope': 'local_simulation_trial_only',
                 'physicalAcceptance': False, 'executionAuthority': 'none',
                 'verificationReport': pin(root, REPORT), 'sourceInputs': report['inputs'],
                 'buildOutputs': report['build_outputs'], 'trialPreparationInputs': [pin(root, n) for n in extras]}
    encode = lambda obj: (json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=True) + '\n').encode()
    candidate_bytes = encode(candidate)
    candidate_digest = hashlib.sha256(candidate_bytes).hexdigest()
    port = readiness['port']
    instructions = f'''# Local maker trial\n\nThis packet references this checkout; it is not a standalone Studio distribution.\nRun from the repository root. Before use run: .venv/bin/python scripts/robotics/prepare_maker_trial.py verify --packet {destination.relative_to(root).as_posix()}.\n\n1. Run: .venv/bin/python scripts/robotics/prepare_maker_trial.py preflight --port {port} --browser-channel {readiness['browserChannel']}\n2. Run: .venv/bin/python scripts/robotics/serve_mini_studio.py --port {port}\n3. Open http://127.0.0.1:{port} in the selected browser and follow lesson.md.\n4. Record actual observations in observation.json. Pending fields are not a pass.\n\nRecovery: stop your own server with Ctrl-C, rerun preflight, then restart the same command.\nRecheck DRC after simulation settings changes before downloading the design ZIP.\nExport a valuable draft before experimenting. Browser draft storage is local to the origin;\nchanging port or clearing site data can hide/remove it. Do not clear site data as recovery.\nDo not force-kill unrelated processes. Do not use git reset or restore over local work.\n\nRollback candidate: stop your server and keep exported drafts. An earlier source revision\nneeds its own separate checkout/build and verification; never mix old source with new dist/.\nSelect and review that revision before building it; this packet does not execute rollback.\nSupport and rollback ownership remain unassigned until an operator supplies them.\n\nUnsigned lesson replay is distinct from the separately configured signed evidence inspector.\nNo human trial completion, release approval, service signing or physical authority is implied.\n'''
    files = {'candidate.json': candidate_bytes, 'preflight.json': encode(readiness),
             'observation.json': encode(observation_template(candidate_digest)),
             'verification.json': local_file(root, REPORT).read_bytes(),
             'lesson.md': local_file(root, extras[2]).read_bytes(), 'README.md': instructions.encode()}
    if sum(map(len, files.values())) > MAX_JSON:
        raise ValueError('Trial packet exceeds 2 MiB')
    manifest = {'schemaVersion': 'seedcore.maker-trial-packet.v1', 'candidateDigest': candidate_digest,
                'preparedAt': datetime.now(timezone.utc).isoformat(), 'status': 'prepared_not_observed',
                'physicalAcceptance': False, 'executionAuthority': 'none', 'releaseDecision': 'defer',
                'files': [{'path': n, 'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest()} for n, b in sorted(files.items())]}
    files['manifest.json'] = encode(manifest)
    destination.mkdir(parents=True, exist_ok=False)
    for name, content in files.items():
        with (destination / name).open('xb') as stream:
            stream.write(content)
    return manifest



def verify_packet(root: Path, folder: Path):
    folder = folder.resolve(strict=True)
    if not folder.is_relative_to(root / 'artifacts/robotics/cw-l02-trials'):
        raise ValueError('Packet outside local trial directory')
    manifest = read_json(folder, 'manifest.json')
    if manifest.get('schemaVersion') != 'seedcore.maker-trial-packet.v1' or manifest.get('status') != 'prepared_not_observed':
        raise ValueError('Invalid trial manifest')
    entries = manifest.get('files', [])
    required = {'candidate.json', 'preflight.json', 'observation.json', 'verification.json', 'lesson.md', 'README.md'}
    if len(entries) != len(required) or {e['path'] for e in entries} != required:
        raise ValueError('Incomplete packet inventory')
    for entry in entries:
        # The observation may be manually filled; it never changes the preparation result.
        if entry['path'] != 'observation.json' and pin(folder, entry['path'])['sha256'] != entry['sha256']:
            raise ValueError('Changed immutable packet file')
    candidate = read_json(folder, 'candidate.json')
    if pin(folder, 'candidate.json')['sha256'] != manifest['candidateDigest']:
        raise ValueError('Candidate binding mismatch')
    if candidate['revision'] != git(root, 'rev-parse', 'HEAD'):
        raise ValueError('Candidate revision changed')
    checked_report(root)
    for entry in [candidate['verificationReport'], *candidate['sourceInputs'], *candidate['buildOutputs'], *candidate['trialPreparationInputs']]:
        if pin(root, entry['path'])['sha256'] != entry['sha256']:
            raise ValueError(f"Candidate checkout changed: {entry['path']}")
    observation = read_json(folder, 'observation.json')
    if (observation.get('schemaVersion') != 'seedcore.maker-observation.v1'
        or observation.get('candidateDigest') != manifest['candidateDigest']
        or observation.get('status') not in ('pending', 'recorded')
        or observation.get('releaseDecision') != 'defer'):
        raise ValueError('Invalid observation binding or implied release approval')
    template = observation_template(manifest['candidateDigest'])
    if not isinstance(observation.get('observations'), dict) or set(observation['observations']) != set(template['observations']):
        raise ValueError('Incomplete observation fields')
    if observation['status'] == 'recorded' and (observation.get('independentAdultMakerObserved') is not True
        or any(value is None or value == '' or value == [] or value == {} for value in observation['observations'].values())):
        raise ValueError('Recorded observation lacks required manual evidence')
    return {'status': 'packet_current', 'candidateDigest': manifest['candidateDigest'],
            'observationStatus': observation['status'], 'humanEvidenceValidated': False, 'releaseDecision': 'defer',
            'note': 'Manual assertions are not independently attested by this tool.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['preflight', 'prepare', 'verify'])
    parser.add_argument('--port', type=int, default=8767)
    parser.add_argument('--browser-channel', choices=['chrome', 'bundled'], default='chrome')
    parser.add_argument('--out', type=Path, help='New directory under artifacts/robotics/cw-l02-trials/; required for prepare')
    parser.add_argument('--packet', type=Path, help='Existing local trial directory for verify')
    args = parser.parse_args()
    try:
        if args.action == 'verify':
            if args.packet is None:
                parser.error('verify requires --packet')
            print(json.dumps(verify_packet(ROOT, args.packet), indent=2))
            return 0
        readiness = preflight(ROOT, args.port, args.browser_channel)
        if args.action == 'prepare':
            if args.out is None:
                parser.error('prepare requires --out')
            result = prepare(ROOT, args.out, readiness)
        else:
            result = readiness
        print(json.dumps(result, indent=2))
        return 0 if readiness['status'] == 'ready' else 1
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(json.dumps({'status': 'blocked', 'reason': str(error)}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

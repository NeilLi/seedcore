"""Test/report adapter for the independent Rust CW verifier; never an authority path."""
import json
import os
from pathlib import Path
import subprocess

from seedcore.robotics.cw_evidence import json_bytes

ROOT = Path(__file__).resolve().parents[2]


def compare(raw, *, expected, trust, python_report, directory):
    """Retain exact input bytes and both reports, including any disagreement."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    paths = {name: directory/(name+'.json') for name in ('bundle', 'expected', 'trust')}
    paths['bundle'].write_bytes(raw)
    paths['expected'].write_bytes(json_bytes(expected))
    paths['trust'].write_bytes(json_bytes(trust))
    (directory/'python.verification.json').write_bytes(json_bytes(python_report))
    result = subprocess.run([os.getenv('SEEDCORE_VERIFY_BIN', str(ROOT/'rust/target/debug/seedcore-verify')),
        'verify-cw-evidence', '--bundle', str(paths['bundle']), '--expected', str(paths['expected']), '--trust', str(paths['trust'])],
        cwd=ROOT, capture_output=True, text=True, timeout=15, check=False)
    (directory/'rust.stdout.txt').write_text(result.stdout)
    (directory/'rust.stderr.txt').write_text(result.stderr)
    report = json.loads(result.stdout)
    (directory/'rust.verification.json').write_bytes(json_bytes(report))
    fields = ['verified', 'disposition', 'scope', 'physicalAcceptance', 'executionAuthority']
    if python_report['verified']:
        fields += ['schemaVersion', 'bundleSha256', 'expectedContextDigest', 'trustSnapshotDigest', 'sourceRefs']
    mismatches = {name: dict(python=python_report.get(name), rust=report.get(name)) for name in fields
                  if python_report.get(name) != report.get(name)}
    if result.returncode != (0 if report.get('verified') is True else 1):
        mismatches['exit_code'] = result.returncode
    summary = dict(agreement=not mismatches, disposition=python_report['disposition'], mismatches=mismatches)
    (directory/'parity.json').write_bytes(json_bytes(summary))
    if mismatches:
        raise AssertionError(f'Python/Rust CW evidence disagreement; retained at {directory}: {mismatches}')
    return report

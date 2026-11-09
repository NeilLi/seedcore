#!/usr/bin/env python3
"""Actual localhost startup/restart and prepared-packet smoke check; no human trial."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime, timezone
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('maker_trial', ROOT / 'scripts/robotics/prepare_maker_trial.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def run():
    out = ROOT / 'artifacts/robotics/cw-l02'
    out.mkdir(parents=True, exist_ok=True)
    port = 8783
    report = {'scope': 'local_simulation_trial_only', 'physicalAcceptance': False, 'executionAuthority': 'none',
              'humanObservation': 'pending', 'releaseDecision': 'defer', 'checks': [], 'startupProbes': []}
    try:
        subprocess.run([sys.executable, '-m', 'pytest', 'tests/test_maker_trial.py', '-q', '--tb=short'], cwd=ROOT, check=True)
        ready = m.preflight(ROOT, port)
        if ready['status'] != 'ready':
            raise ValueError(json.dumps(ready))
        report['checks'].append('fresh accepted build, dependencies, browser and free localhost port')
        name = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        trial = ROOT / 'artifacts/robotics/cw-l02-trials' / name
        m.prepare(ROOT, trial, ready)
        m.verify_packet(ROOT, trial)
        report['trialPacket'] = trial.relative_to(ROOT).as_posix()
        report['checks'].append('new source-bound packet with pending human observation and deferred release')
        for attempt in range(2):
            log = out / f'startup-{attempt + 1}.log'
            started = time.monotonic()
            with log.open('wb') as stream:
                process = subprocess.Popen([sys.executable, 'scripts/robotics/serve_mini_studio.py', '--port', str(port)],
                                           cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
                try:
                    for _ in range(100):
                        if process.poll() is not None:
                            raise ValueError('Owned Studio process exited before readiness')
                        try:
                            with urlopen(f'http://127.0.0.1:{port}/', timeout=0.5) as response:
                                html = response.read(1024 * 1024).decode()
                                assert 'Guided lesson' in html and 'gallery-synthetic' in html
                                assert 'script-src' in response.headers.get('Content-Security-Policy', '')
                            break
                        except OSError:
                            time.sleep(0.1)
                    else:
                        raise ValueError('Studio readiness timed out')
                    report['startupProbes'].append({'attempt': attempt + 1, 'automatedStartupSeconds': round(time.monotonic() - started, 3)})
                    with urlopen(f'http://127.0.0.1:{port}/api/simulation-reference', timeout=2) as response:
                        reference = json.loads(response.read(262144))
                        assert reference['physicalAcceptance'] is False and reference['executionAuthority'] == 'none'
                    busy = m.preflight(ROOT, port)
                    assert busy['status'] == 'blocked'
                    assert any(c['name'] == 'Local port available' and not c['ok'] for c in busy['checks'])
                    with urlopen(f'http://127.0.0.1:{port}/', timeout=2) as response:
                        assert response.status == 200
                    # Verify can run while Studio is open; it does not require or reclaim a free port.
                    result = subprocess.run([sys.executable, 'scripts/robotics/prepare_maker_trial.py', 'verify', '--packet', str(trial)],
                                            cwd=ROOT, capture_output=True, text=True, timeout=15, check=True)
                    assert json.loads(result.stdout)['observationStatus'] == 'pending'
                finally:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)
            report['checks'].append(f'owned localhost startup {attempt + 1}, occupied-port refusal without service interruption, packet verification and graceful stop')
        stopped = m.preflight(ROOT, port)
        if stopped['status'] != 'ready':
            raise ValueError('Post-stop preflight failed: ' + json.dumps(stopped))
        report['checks'].append('port available after owned server stop; restart preserved source/build bindings')
        report['status'] = 'checks_passed'
    except Exception as error:
        report['status'] = 'checks_failed'
        report['failure'] = f'{type(error).__name__}: {error}'
    report['candidateVerification'] = m.pin(ROOT, 'artifacts/robotics/cw-l01/verification.json')
    report['toolInputs'] = [m.pin(ROOT, n) for n in ['scripts/robotics/prepare_maker_trial.py',
                           'tools/robotics/verify-cw-l02-trial.py', 'tests/test_maker_trial.py']]
    (out / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return 0 if report['status'] == 'checks_passed' else 1


if __name__ == '__main__':
    raise SystemExit(run())

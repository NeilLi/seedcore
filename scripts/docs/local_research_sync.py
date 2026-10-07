#!/usr/bin/env python3
"""Local private-document sync: fetch autonomously, apply only an approved digest."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import difflib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import signal
import subprocess
import sys
import tempfile

if __package__:
    from . import sync_research_report as report
    from .private_drive_report import DEFAULT_CREDENTIALS, fetch_private_document
else:
    import sync_research_report as report
    from private_drive_report import DEFAULT_CREDENTIALS, fetch_private_document

STATE_DIR = Path.home() / "Library/Application Support/SeedCore/research-sync"
LABEL = "ai.seedcore.research-sync"
SCHEMA = "seedcore.local-research-candidate.v1"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_write(path: Path, data: bytes, mode=0o600):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".sync-", delete=False) as file:
            temporary = Path(file.name)
            file.write(data); file.flush(); os.fsync(file.fileno())
        temporary.chmod(mode)
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def load_json(path: Path):
    return json.loads(path.read_text()) if path.exists() else {}


def write_json(path: Path, value):
    atomic_write(path, (json.dumps(value, indent=2) + "\n").encode())


@contextmanager
def locked(state_dir: Path):
    # A private source must never land in a Git checkout, even an ignored folder.
    resolved = state_dir.resolve()
    if any((parent / ".git").exists() for parent in [resolved, *resolved.parents]):
        raise report.SyncError("State directory must be outside every Git checkout.")
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    state_dir.chmod(0o700)
    with (state_dir / ".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise report.SyncError("Another local sync operation is running.") from error
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def due_period(now: datetime) -> str:
    monday = (now - timedelta(days=now.weekday())).replace(hour=3, minute=0, second=0, microsecond=0)
    if now < monday:
        monday -= timedelta(days=7)
    return monday.isoformat()


def run_once(state_dir: Path, credentials: Path, *, scheduled=False, fetcher=fetch_private_document, target=report.OUTPUT_PATH, now=None):
    now = now or datetime.now(timezone.utc)
    with locked(state_dir):
        status = load_json(state_dir / "status.json")
        if status.get("consecutive_failures", 0) >= 3:
            raise report.SyncError("Sync suspended after three failures. Repair access, then run resume.")
        period = due_period(now)
        if scheduled and status.get("completed_period") == period:
            return "not-due"
        status["last_attempt"] = now.isoformat()
        try:
            content, source = fetcher(report.DOCUMENT_ID, credentials)
            baseline = target.read_bytes() if target.exists() else b""
            previous = load_json(state_dir / "candidate.json")
            source_sha = digest(content.encode())
            base_sha = digest(baseline)
            stamp = now.strftime("%Y-%m-%d %H:%M:%S UTC")
            old_stamp = re.search(r"^\*\*Last synced:\*\* ([^\n]+)$", baseline.decode("utf-8"), re.MULTILINE)
            if old_stamp:
                stamp = old_stamp[1]
            candidate_text = report.render_report(content, report.DOCUMENT_ID, "md", stamp)
            if candidate_text.encode() == baseline:
                outcome = "unchanged"
                # A stale pending candidate must never survive a source revert.
                (state_dir / "candidate.json").unlink(missing_ok=True)
            else:
                if not (previous.get("schema") == SCHEMA and previous.get("document_id") == report.DOCUMENT_ID and
                        isinstance(previous.get("report"), str) and digest(previous["report"].encode()) == previous.get("candidate_sha256") and
                        previous.get("base_sha256") == base_sha and previous.get("source_sha256") == source_sha):
                    candidate_text = report.render_report(content, report.DOCUMENT_ID, "md", now.strftime("%Y-%m-%d %H:%M:%S UTC"))
                    previous = {"schema": SCHEMA, "document_id": report.DOCUMENT_ID,
                                "created_at": now.isoformat(), "base_sha256": base_sha, "source_sha256": source_sha,
                                "candidate_sha256": digest(candidate_text.encode()), "source": source, "report": candidate_text}
                    write_json(state_dir / "candidate.json", previous)
                outcome = "pending-review"
            status.update(last_success=now.isoformat(), completed_period=period, consecutive_failures=0,
                          outcome=outcome, last_error=None, source=source)
        except Exception as error:
            # Keep the last valid candidate; status makes failed freshness visible.
            message = str(error) if isinstance(error, report.SyncError) else "Local sync failed; check file permissions, credentials and connectivity."
            status.update(consecutive_failures=status.get("consecutive_failures", 0)+1, last_error=message, outcome="error")
            write_json(state_dir / "status.json", status)
            raise report.SyncError(message) from error
        write_json(state_dir / "status.json", status)
        return outcome


def candidate(state_dir: Path, target=report.OUTPUT_PATH):
    value = load_json(state_dir / "candidate.json")
    if (value.get("schema") != SCHEMA or value.get("document_id") != report.DOCUMENT_ID or
            not isinstance(value.get("report"), str) or digest(value["report"].encode()) != value.get("candidate_sha256")):
        raise report.SyncError("No valid candidate. Run a successful sync first.")
    current = target.read_bytes() if target.exists() else b""
    if digest(current) != value.get("base_sha256"):
        raise report.SyncError("Repository report changed since this candidate was prepared. Fetch and review again.")
    return value, current


def apply_candidate(state_dir: Path, approved_sha: str, target=report.OUTPUT_PATH):
    with locked(state_dir):
        value, _ = candidate(state_dir, target)
        if approved_sha != value["candidate_sha256"]:
            raise report.SyncError("Approved SHA-256 does not match the current candidate. Review again.")
        # Refuse stale success after any subsequent fetch failure.
        if load_json(state_dir / "status.json").get("outcome") != "pending-review":
            raise report.SyncError("Latest sync was not successful. Fetch and review again before applying.")
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(target, value["report"].encode(), 0o644)
        (state_dir / "candidate.json").unlink()
        status = load_json(state_dir / "status.json")
        status.update(outcome="applied-locally", applied_sha256=approved_sha)
        write_json(state_dir / "status.json", status)


def launch_agent(python: Path, credentials: Path, state_dir: Path):
    return {"Label": LABEL, "ProgramArguments": [str(python.absolute()), str(Path(__file__).resolve()),
            "--state-dir", str(state_dir.resolve()), "--credentials", str(credentials.resolve()), "run", "--scheduled"],
            "WorkingDirectory": str(report.ROOT), "RunAtLoad": True, "StartInterval": 3600,
            "ProcessType": "Background", "Umask": 0o077,
            "StandardOutPath": str(state_dir.resolve()/"agent.log"), "StandardErrorPath": str(state_dir.resolve()/"agent.log")}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, default=STATE_DIR)
    parser.add_argument("--credentials", type=Path, default=DEFAULT_CREDENTIALS)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Fetch once now; no scheduler installation required.")
    run.add_argument("--scheduled", action="store_true", help="Skip a weekly period that already succeeded (used by LaunchAgent).")
    sub.add_parser("check")
    sub.add_parser("status")
    sub.add_parser("review")
    sub.add_parser("resume")
    apply = sub.add_parser("apply"); apply.add_argument("--approve-sha256", required=True)
    sub.add_parser("install")
    sub.add_parser("uninstall")
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            content, source = fetch_private_document(report.DOCUMENT_ID, args.credentials)
            print(json.dumps({"verified": True, "bytes": len(content.encode()), "source": source}))
        elif args.command == "run":
            print(run_once(args.state_dir, args.credentials, scheduled=args.scheduled))
        elif args.command == "apply":
            apply_candidate(args.state_dir, args.approve_sha256)
            print("Candidate applied locally. Review the Git diff before publishing.")
        elif args.command == "install":
            if sys.platform != "darwin":
                raise report.SyncError("LaunchAgent installation requires macOS.")
            destination = Path.home()/"Library/LaunchAgents"/f"{LABEL}.plist"
            if destination.exists():
                raise report.SyncError("LaunchAgent already exists. Inspect or uninstall it before replacing it.")
            # An actual successful private export is mandatory before installation.
            run_once(args.state_dir, args.credentials)
            destination.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(destination, plistlib.dumps(launch_agent(Path(sys.executable), args.credentials, args.state_dir)))
            result = subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(destination)], capture_output=True)
            if result.returncode:
                destination.unlink()
                raise report.SyncError("launchctl bootstrap failed; no new plist was retained.")
            print(f"Installed {LABEL}. Private candidates await local review.")
        elif args.command == "uninstall":
            destination = Path.home()/"Library/LaunchAgents"/f"{LABEL}.plist"
            if destination.exists():
                result = subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"], capture_output=True)
                if result.returncode:
                    raise report.SyncError("Could not unload LaunchAgent; inspect launchctl before removing its plist.")
                destination.unlink()
            print("LaunchAgent removed; local candidates and credentials retained.")
        else:
            with locked(args.state_dir):
                status = load_json(args.state_dir/"status.json")
                if args.command == "resume":
                    status.update(consecutive_failures=0, last_error=None)
                    write_json(args.state_dir/"status.json", status)
                    print("Retry enabled. Run sync again to verify access.")
                elif args.command == "status":
                    value = load_json(args.state_dir/"candidate.json")
                    print(json.dumps({**status, "candidate_sha256": value.get("candidate_sha256")}, indent=2))
                else:
                    value, current = candidate(args.state_dir)
                    print(f"Candidate SHA-256: {value['candidate_sha256']}")
                    print(f"Fetched: {value['created_at']}; Google version: {value['source']['version']}")
                    print("".join(difflib.unified_diff(current.decode().splitlines(True), value["report"].splitlines(True),
                                                     fromfile="repository report", tofile="private candidate")))
        return 0
    except (report.SyncError, OSError, ValueError) as error:
        print(str(error) if isinstance(error, report.SyncError) else "Local operation failed; inspect paths and permissions.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    # Bound unattended networking even if a provider trickles bytes indefinitely.
    def timeout_handler(signum, frame):
        raise report.SyncError("Local sync exceeded its three-minute execution budget.")
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(180)
    raise SystemExit(main())

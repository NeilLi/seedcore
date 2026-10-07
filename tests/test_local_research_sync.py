"""Private fetch, local candidate and approval boundaries; no credentials/network."""
from datetime import datetime, timedelta, timezone
from email.message import Message
from io import BytesIO
import json
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts.docs import local_research_sync as agent
from scripts.docs import private_drive_report as drive
from scripts.docs import sync_research_report as report


class Response(BytesIO):
    def __init__(self, body, status=200, mime="application/json"):
        super().__init__(body)
        self.status = status
        self.headers = Message(); self.headers["Content-Type"] = mime


class Opener:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def open(self, request, timeout):
        self.requests.append(request)
        return next(self.responses)


def metadata(**changes):
    return {"id": report.DOCUMENT_ID, "mimeType": drive.DOC_MIME, "version": "1",
            "modifiedTime": "2026-10-07T00:00:00Z", "trashed": False,
            "capabilities": {"canDownload": True}, **changes}


def meta_response(**changes):
    return Response(json.dumps(metadata(**changes)).encode())


class PrivateDriveTests(unittest.TestCase):
    def fetch(self, opener):
        return drive.fetch_private_document(report.DOCUMENT_ID, Path("unused"), opener=opener, token_provider=lambda _: "test-token")

    def test_metadata_export_metadata_binds_one_private_doc_without_exposing_token(self):
        opener = Opener([meta_response(), Response(b"# Private research\n", mime="text/markdown"), meta_response()])
        text, source = self.fetch(opener)
        self.assertEqual(text, "# Private research\n")
        self.assertEqual(source["version"], "1")
        self.assertNotIn("test-token", json.dumps(source))
        for request in opener.requests:
            self.assertTrue(request.full_url.startswith("https://www.googleapis.com/drive/v3/files/" + report.DOCUMENT_ID))
            self.assertEqual(request.get_header("Authorization"), "Bearer test-token")

    def test_bearer_redirect_is_never_followed(self):
        opener = Opener([Response(b"", status=302)])
        with self.assertRaisesRegex(report.SyncError, "not forwarded"):
            self.fetch(opener)
        self.assertEqual(len(opener.requests), 1)

    def test_missing_scope_or_access_fails_without_reading_body(self):
        for status in (401, 403, 404, 500):
            with self.subTest(status=status), self.assertRaises(report.SyncError):
                self.fetch(Opener([Response(b"sensitive-provider-message", status=status)]))

    def test_wrong_type_id_export_permission_or_trashed_document_is_rejected(self):
        for changes in [{"id": "other"}, {"mimeType": "application/pdf"}, {"trashed": True},
                        {"capabilities": {"canDownload": False}}, {"version": None}]:
            with self.subTest(changes=changes), self.assertRaises(report.SyncError):
                self.fetch(Opener([meta_response(**changes)]))

    def test_document_changed_during_export_is_not_accepted(self):
        with self.assertRaisesRegex(report.SyncError, "changed during export"):
            self.fetch(Opener([meta_response(), Response(b"# report", mime="text/markdown"), meta_response(version="2")]))

    def test_mislabeled_login_html_reuses_export_validation(self):
        with self.assertRaisesRegex(report.SyncError, "HTML"):
            self.fetch(Opener([meta_response(), Response(b"<html>login</html>", mime="text/plain")]))


class LocalAgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / "private"
        self.target = self.root / "repo/report.md"
        self.target.parent.mkdir(); self.target.write_text("# Existing report\n")
        self.now = datetime(2026, 10, 7, 10, tzinfo=timezone.utc)
        self.fetcher = Mock(return_value=("# Private source\n", {"version": "7", "document_id": report.DOCUMENT_ID}))

    def run_sync(self, **kwargs):
        return agent.run_once(self.state, Path("unused"), fetcher=self.fetcher, target=self.target, now=self.now, **kwargs)

    def value(self):
        return agent.load_json(self.state/"candidate.json")

    def test_private_candidate_never_changes_repository_and_has_private_permissions(self):
        original = self.target.read_bytes()
        self.assertEqual(self.run_sync(), "pending-review")
        self.assertEqual(self.target.read_bytes(), original)
        self.assertIn("# Private source", self.value()["report"])
        self.assertEqual(self.state.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.state/"candidate.json").stat().st_mode & 0o777, 0o600)

    def test_same_candidate_keeps_approval_digest_and_no_timestamp_churn(self):
        self.run_sync(); original = self.value()
        self.now += timedelta(days=1); self.run_sync()
        self.assertEqual(self.value(), original)

    def test_wrong_approval_digest_and_changed_baseline_are_rejected(self):
        self.run_sync(); sha = self.value()["candidate_sha256"]
        with self.assertRaisesRegex(report.SyncError, "Approved SHA"):
            agent.apply_candidate(self.state, "0"*64, self.target)
        self.target.write_text("concurrent user edit")
        with self.assertRaisesRegex(report.SyncError, "Repository report changed"):
            agent.apply_candidate(self.state, sha, self.target)
        self.assertEqual(self.target.read_text(), "concurrent user edit")

    def test_changed_candidate_requires_new_approval(self):
        self.run_sync(); sha = self.value()["candidate_sha256"]
        self.fetcher.return_value = ("# New source\n", {"version": "8"})
        self.run_sync()
        with self.assertRaisesRegex(report.SyncError, "Approved SHA"):
            agent.apply_candidate(self.state, sha, self.target)

    def test_only_matching_approval_copies_exact_candidate_locally(self):
        self.run_sync(); value = self.value()
        agent.apply_candidate(self.state, value["candidate_sha256"], self.target)
        self.assertEqual(self.target.read_text(), value["report"])
        self.assertFalse((self.state/"candidate.json").exists())
        self.assertEqual(agent.load_json(self.state/"status.json")["outcome"], "applied-locally")
        self.assertEqual(self.run_sync(), "unchanged")

    def test_source_revert_clears_obsolete_pending_candidate(self):
        self.run_sync(); value = self.value()
        agent.apply_candidate(self.state, value["candidate_sha256"], self.target)
        original = self.fetcher.return_value
        self.fetcher.return_value = ("# Temporary source\n", {"version": "9"})
        self.run_sync()
        self.fetcher.return_value = original
        self.assertEqual(self.run_sync(), "unchanged")
        self.assertFalse((self.state/"candidate.json").exists())

    def test_failed_fetch_preserves_candidate_blocks_apply_and_suspends_after_three(self):
        self.run_sync(); value = self.value()
        self.fetcher.side_effect = report.SyncError("Private Drive HTTP 403")
        for _ in range(3):
            with self.assertRaises(report.SyncError): self.run_sync()
            self.assertEqual(self.value(), value)
        self.fetcher.reset_mock()
        with self.assertRaisesRegex(report.SyncError, "suspended"): self.run_sync()
        self.fetcher.assert_not_called()
        with self.assertRaisesRegex(report.SyncError, "Latest sync"):
            agent.apply_candidate(self.state, value["candidate_sha256"], self.target)

    def test_unknown_exception_does_not_persist_sensitive_details(self):
        self.fetcher.side_effect = RuntimeError("access-token-secret")
        with self.assertRaises(report.SyncError): self.run_sync()
        self.assertNotIn("access-token-secret", (self.state/"status.json").read_text())

    def test_concurrent_run_and_state_inside_git_checkout_are_rejected(self):
        with agent.locked(self.state):
            with self.assertRaisesRegex(report.SyncError, "Another local sync"):
                self.run_sync()
        (self.target.parent/".git").mkdir()
        with self.assertRaisesRegex(report.SyncError, "outside every Git"):
            with agent.locked(self.target.parent/"state"): pass

    def test_tampered_candidate_is_rejected_and_next_fetch_repairs_it(self):
        self.run_sync(); value = self.value()
        value["report"] = "tampered"
        agent.write_json(self.state/"candidate.json", value)
        with self.assertRaisesRegex(report.SyncError, "No valid candidate"):
            agent.apply_candidate(self.state, value["candidate_sha256"], self.target)
        self.run_sync()
        self.assertNotEqual(self.value()["report"], "tampered")

    def test_utc_weekly_schedule_skips_completed_period_and_catches_up_after_sleep(self):
        self.assertEqual(agent.due_period(datetime(2026, 10, 12, 2, tzinfo=timezone.utc)), "2026-10-05T03:00:00+00:00")
        self.run_sync(scheduled=True); self.fetcher.reset_mock()
        self.assertEqual(self.run_sync(scheduled=True), "not-due"); self.fetcher.assert_not_called()
        self.now += timedelta(days=7)
        self.assertEqual(self.run_sync(scheduled=True), "pending-review"); self.fetcher.assert_called_once()

    def test_manual_run_fetches_again_in_completed_week_without_launch_agent(self):
        self.run_sync(scheduled=True)
        self.fetcher.reset_mock()
        self.fetcher.return_value = ("# Updated while online\n", {"version": "8"})
        with patch.object(agent.subprocess, "run") as launch:
            self.assertEqual(self.run_sync(), "pending-review")
            launch.assert_not_called()
        self.fetcher.assert_called_once()
        self.assertIn("Updated while online", self.value()["report"])
        self.assertEqual(self.target.read_text(), "# Existing report\n")

    def test_launch_agent_uses_absolute_paths_no_shell_and_scheduled_local_run(self):
        value = agent.launch_agent(Path("/local python/bin/python"), Path("/private credentials.json"), self.state)
        self.assertEqual(plistlib.loads(plistlib.dumps(value)), value)
        self.assertEqual(value["ProgramArguments"][-2:], ["run", "--scheduled"])
        self.assertEqual(value["Umask"], 0o077)
        self.assertEqual(value["StartInterval"], 3600)
        self.assertNotIn("KeepAlive", value)

    def test_installation_requires_real_successful_preflight(self):
        with patch.object(agent, "run_once", side_effect=report.SyncError("no access")), \
             patch.object(agent.Path, "home", return_value=self.root), patch.object(agent.sys, "platform", "darwin"), \
             patch.object(agent.subprocess, "run") as launch:
            self.assertEqual(agent.main(["--state-dir", str(self.state), "install"]), 1)
            launch.assert_not_called()
            self.assertFalse((self.root/"Library/LaunchAgents").exists())


if __name__ == "__main__":
    unittest.main()

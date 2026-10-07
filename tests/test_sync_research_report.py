"""Offline export regressions; runnable with unittest without runtime packages."""

from contextlib import redirect_stderr
from datetime import datetime, timezone
from email.message import Message
from http.client import IncompleteRead
from io import BytesIO, StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from scripts.docs import sync_research_report as sync


class Response(BytesIO):
    def __init__(self, body=b"# Research\n\nA [paper](https://example.com).\n", status=200, media_type="text/markdown", **headers):
        super().__init__(body)
        self.status = status
        self.headers = Message()
        if media_type is not None:
            self.headers["Content-Type"] = media_type
        for name, value in headers.items():
            self.headers[name.replace("_", "-")] = value


class Opener:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request.full_url, timeout))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


class ResearchSyncTests(unittest.TestCase):
    def test_markdown_export_preserves_structure_unicode_and_normalizes_line_endings(self):
        body = "\ufeff# Research\r\n\r\n| Robot | Model |\r\n| --- | --- |\r\n| 鸭 | **v1** |\r\n\r\n[Paper](https://example.com)\r\n"
        opener = Opener(Response(body.encode("utf-8"), media_type="text/markdown; charset=utf-8"))
        text = sync.fetch_document(sync.DOCUMENT_ID, opener=opener)
        self.assertEqual(text, body.lstrip("\ufeff").replace("\r\n", "\n"))
        self.assertTrue(opener.requests[0][0].endswith("export?format=md"))
        self.assertEqual(opener.requests[0][1], 30)

    def test_follows_relative_and_google_export_redirects_including_308(self):
        opener = Opener(Response(status=302, Location="/document/export-ready"),
                        Response(status=308, Location="https://doc-test.googleusercontent.com/export"), Response())
        sync.fetch_document(sync.DOCUMENT_ID, opener=opener)
        self.assertEqual(len(opener.requests), 3)
        self.assertEqual(opener.requests[1][0], "https://docs.google.com/document/export-ready")

    def test_authentication_redirect_at_later_hop_is_never_requested(self):
        opener = Opener(Response(status=303, Location="https://doc-test.googleusercontent.com/export"),
                        Response(status=307, Location="https://accounts.google.com/ServiceLogin"))
        with self.assertRaisesRegex(sync.SyncError, "anonymously readable"):
            sync.fetch_document(sync.DOCUMENT_ID, opener=opener)
        self.assertEqual(len(opener.requests), 2)

    def test_refuses_unexpected_redirect_hosts_insecure_urls_and_embedded_credentials(self):
        for location in ["https://attacker.example/report", "http://docs.google.com/export",
                         "https://docs.google.com.attacker.example/export", "https://user:pass@docs.google.com/export",
                         "https://docs.google.com:444/export", "//accounts.google.com/ServiceLogin"]:
            with self.subTest(location=location):
                opener = Opener(Response(status=301, Location=location))
                with self.assertRaises(sync.SyncError):
                    sync.fetch_document(sync.DOCUMENT_ID, opener=opener)
                self.assertEqual(len(opener.requests), 1)

    def test_missing_location_and_redirect_loops_are_bounded(self):
        with self.assertRaisesRegex(sync.SyncError, "Location"):
            sync.fetch_document(sync.DOCUMENT_ID, opener=Opener(Response(status=302)))
        opener = Opener(*(Response(status=302, Location="/again") for _ in range(sync.MAX_REDIRECTS + 1)))
        with self.assertRaisesRegex(sync.SyncError, "Too many"):
            sync.fetch_document(sync.DOCUMENT_ID, opener=opener)
        self.assertEqual(len(opener.requests), sync.MAX_REDIRECTS + 1)

    def test_real_urllib_http_errors_are_processed_as_responses(self):
        response = Response(status=302, Location="https://doc-test.googleusercontent.com/export")
        error = HTTPError("https://docs.google.com/export", 302, "Found", response.headers, BytesIO())
        sync.fetch_document(sync.DOCUMENT_ID, opener=Opener(error, Response()))
        for status in [401, 403, 404, 429, 500, 204]:
            with self.subTest(status=status):
                error = HTTPError("https://docs.google.com/export", status, "error", Message(), BytesIO())
                with self.assertRaises(sync.SyncError):
                    sync.fetch_document(sync.DOCUMENT_ID, opener=Opener(error))

    def test_html_missing_content_type_binary_empty_and_invalid_utf8_are_rejected(self):
        for body, mime in [(b"<html>Sign in</html>", "text/html"),
                           (b"# Research", None), (b"PK\x00\x01", "application/zip"),
                           (b" \n", "text/plain"), (b"\xff", "text/plain"), (b"report\x00", "text/plain"),
                           (b"<!DOCTYPE html><html>Sign in</html>", "text/plain"),
                           (b"<!-- comment -->\n<HTML>Sign in</HTML>", "text/markdown")]:
            with self.subTest(body=body, mime=mime):
                with self.assertRaises(sync.SyncError):
                    sync.fetch_document(sync.DOCUMENT_ID, opener=Opener(Response(body, media_type=mime)))

    def test_oversize_and_truncated_responses_are_rejected(self):
        for headers in [{"Content_Length": "100"}, {"Content_Length": "bad"},
                        {"Content_Length": str(sync.MAX_BYTES + 1)}]:
            with self.subTest(headers=headers):
                with self.assertRaises(sync.SyncError):
                    sync.fetch_document(sync.DOCUMENT_ID, opener=Opener(Response(b"short", **headers)))
        with patch.object(sync, "MAX_BYTES", 4):
            with self.assertRaisesRegex(sync.SyncError, "exceeds"):
                sync.fetch_document(sync.DOCUMENT_ID, opener=Opener(Response(b"large")))

    def test_network_and_partial_read_errors_are_explicit(self):
        for error in [URLError("timeout"), TimeoutError(), IncompleteRead(b"partial")]:
            with self.subTest(error=error):
                with self.assertRaises(sync.SyncError):
                    sync.fetch_document(sync.DOCUMENT_ID, opener=Opener(error))
        with patch.object(Response, "read", side_effect=IncompleteRead(b"partial")):
            with self.assertRaisesRegex(sync.SyncError, "read completely"):
                sync.fetch_document(sync.DOCUMENT_ID, opener=Opener(Response()))

    def test_invalid_id_is_rejected_before_network_access(self):
        for document_id in ["", "../bad", "https://docs.google.com/", "x" * 201]:
            opener = Opener()
            with self.assertRaises(sync.SyncError):
                sync.fetch_document(document_id, opener=opener)
            self.assertEqual(opener.requests, [])

    def test_success_is_atomic_and_unchanged_content_preserves_timestamp_and_mtime(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "reports/report.md"
            first = datetime(2026, 10, 7, tzinfo=timezone.utc)
            self.assertTrue(sync.sync_report(output, opener=Opener(Response()), now=first))
            original = output.read_bytes()
            mtime = output.stat().st_mtime_ns
            with patch.object(sync.os, "replace") as replace:
                self.assertFalse(sync.sync_report(output, opener=Opener(Response()), now=datetime(2026, 10, 14, tzinfo=timezone.utc)))
                replace.assert_not_called()
            self.assertEqual(output.read_bytes(), original)
            self.assertEqual(output.stat().st_mtime_ns, mtime)
            self.assertIn(b"2026-10-07 00:00:00 UTC", original)
            self.assertIn(b"Source content SHA-256", original)
            self.assertEqual(list(output.parent.glob(".research-sync-*")), [])
            self.assertTrue(sync.sync_report(output, opener=Opener(Response(b"# Changed\n")), now=first))
            self.assertIn("# Changed", output.read_text())

    def test_failed_fetch_never_creates_or_replaces_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "nested/report.md"
            with self.assertRaises(sync.SyncError):
                sync.sync_report(output, opener=Opener(Response(status=401)))
            self.assertFalse(output.parent.exists())
            output.parent.mkdir(); output.write_text("last good report")
            with self.assertRaises(sync.SyncError):
                sync.sync_report(output, opener=Opener(Response(b"<html>login</html>", media_type="text/html")))
            self.assertEqual(output.read_text(), "last good report")

    def test_failed_atomic_replace_preserves_report_and_cleans_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.md"; output.write_text("last good report")
            with patch.object(sync.os, "replace", side_effect=PermissionError("denied")):
                with self.assertRaises(PermissionError):
                    sync.sync_report(output, opener=Opener(Response()))
            self.assertEqual(output.read_text(), "last good report")
            self.assertEqual(list(output.parent.glob(".research-sync-*")), [])

    def test_plain_text_is_labeled_and_fenced_without_losing_indentation(self):
        body = b"    indented text\n```\n# Literal heading\n````\n"
        text = sync.fetch_document(sync.DOCUMENT_ID, "txt", opener=Opener(Response(body, media_type="text/plain")))
        result = sync.render_report(text, sync.DOCUMENT_ID, "txt", "2026-10-07")
        self.assertIn("native formatting is not preserved", result)
        self.assertIn("`````text\n    indented text\n", result)
        self.assertTrue(result.endswith("`````\n"))

    def test_cli_errors_exit_nonzero_with_an_actionable_message(self):
        stderr = StringIO()
        with patch.object(sync, "sync_report", side_effect=sync.SyncError(sync.ACCESS_ERROR)), redirect_stderr(stderr):
            self.assertEqual(sync.main([]), 1)
        self.assertIn("Anyone with the link can view", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()

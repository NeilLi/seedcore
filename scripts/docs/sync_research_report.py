#!/usr/bin/env python3
"""Sync a publicly readable Google Doc into the external reports index.

Standard-library only. A failed export never replaces the last good report.
"""

from __future__ import annotations

import argparse
import hashlib
from http.client import HTTPException
import os
from pathlib import Path
import re
import sys
import tempfile
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

DOCUMENT_ID = "1bmNZjWUA6_rjFAl2_VT27XZO_9zCU9EpirFXEJM7YNU"
ROOT = Path(__file__).resolve().parents[2]
OUTPUT_PATH = ROOT / "docs/development/reports/embodied_ai_research_report.md"
MAX_BYTES = 10 * 1024 * 1024
MAX_REDIRECTS = 5
REDIRECTS = {301, 302, 303, 307, 308}
ACCESS_ERROR = (
    "Google Doc is not anonymously readable. Verify 'Anyone with the link can view' "
    "and that export/download is permitted, or use a separately configured authenticated integration."
)


class SyncError(RuntimeError):
    """An export failed validation; no output should be written."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_export_url(url: str) -> None:
    """Follow only HTTPS Google export hosts, never a sign-in redirect."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if host == "accounts.google.com":
        raise SyncError(ACCESS_ERROR)
    if (
        parts.scheme != "https"
        or parts.username is not None
        or parts.password is not None
        or parts.port not in (None, 443)
        or not (
            host in {"docs.google.com", "drive.usercontent.google.com"}
            or host.endswith(".googleusercontent.com")
        )
    ):
        raise SyncError("Refusing an unexpected export redirect host or transport.")


def fetch_document(document_id: str, export_format: str = "md", *, opener=None) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,200}", document_id):
        raise SyncError("Invalid Google document ID.")
    if export_format not in {"md", "txt"}:
        raise SyncError("Export format must be md or txt.")
    url = f"https://docs.google.com/document/d/{document_id}/export?format={export_format}"
    opener = opener or build_opener(NoRedirect())
    for hop in range(MAX_REDIRECTS + 1):
        validate_export_url(url)
        request = Request(url, headers={"Accept": "text/markdown, text/plain", "User-Agent": "SeedCore-Research-Sync/1"})
        try:
            response = opener.open(request, timeout=30)
        except HTTPError as error:
            response = error  # Redirects also arrive as HTTPError with NoRedirect.
        except (URLError, TimeoutError, OSError, HTTPException) as error:
            raise SyncError("Could not fetch the Google Doc export (network error or timeout).") from error
        with response:
            if response.status in {401, 403}:
                raise SyncError(ACCESS_ERROR)
            if response.status in REDIRECTS:
                location = response.headers.get("Location")
                if not location:
                    raise SyncError("Export redirect has no Location header.")
                url = urljoin(url, location)
                validate_export_url(url)
                if hop == MAX_REDIRECTS:
                    raise SyncError("Too many export redirects.")
                continue
            if response.status != 200:
                raise SyncError(f"Export failed with HTTP {response.status}.")
            return read_export(response)
    raise SyncError("Too many export redirects.")


def read_export(response) -> str:
    """Validate a successful public or authenticated export before any write."""
    media_type = response.headers.get("Content-Type", "").partition(";")[0].strip().lower()
    if media_type not in {"text/plain", "text/markdown"}:
        raise SyncError("Expected a text/Markdown export; refusing HTML, binary or missing Content-Type.")
    declared_length = response.headers.get("Content-Length")
    if declared_length is not None:
        if not re.fullmatch(r"\d+", declared_length):
            raise SyncError("Export has an invalid Content-Length.")
        declared_length = int(declared_length)
        if declared_length > MAX_BYTES:
            raise SyncError("Export exceeds the 10 MiB report limit.")
    try:
        body = response.read(MAX_BYTES + 1)
    except (URLError, TimeoutError, OSError, HTTPException) as error:
        raise SyncError("Google Doc export could not be read completely.") from error
    if len(body) > MAX_BYTES:
        raise SyncError("Export exceeds the 10 MiB report limit.")
    if declared_length is not None and len(body) != declared_length:
        raise SyncError("Export body is truncated or does not match Content-Length.")
    try:
        content = body.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
    except UnicodeDecodeError as error:
        raise SyncError("Export is not valid UTF-8 text.") from error
    if not content.strip():
        raise SyncError("Export is empty.")
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", content):
        raise SyncError("Export contains binary/control characters.")
    if re.match(r"(?is)\s*(?:<!--.*?-->\s*)*<(?:!doctype\s+html\b|html\b|head\b|body\b|script\b)", content):
        raise SyncError("Export contains an HTML page despite its text Content-Type.")
    return content + "\n"


def render_report(content: str, document_id: str, export_format: str, synced_at: str) -> str:
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    description = "Markdown" if export_format == "md" else "Plain text (native formatting is not preserved)"
    header = (
        "# Embodied AI & Mini Robotics Research Report\n\n"
        "**Status:** Synchronized external reference; source claims are not independently verified.  \n"
        f"**Last synced:** {synced_at}\n"
        f"**Source document:** [Google Doc](https://docs.google.com/document/d/{document_id}/edit)  \n"
        f"**Source export:** {description}  \n"
        f"**Source content SHA-256:** `{digest}`  \n"
        "**Scope:** Literature, models and mini robotics instructions; this report does not change runtime authority, "
        "implementation status or simulator acceptance gates.\n\n---\n\n"
    )
    if export_format == "txt":
        # Keep source text literal, even if it contains Markdown fence characters.
        longest = max((len(match[0]) for match in re.finditer(r"`+", content)), default=0)
        fence = "`" * max(3, longest + 1)
        return header + f"{fence}text\n{content}{fence}\n"
    return header + content


def sync_report(output: Path = OUTPUT_PATH, document_id: str = DOCUMENT_ID, export_format: str = "md", *, opener=None, now=None) -> bool:
    # Fetch and validate first. Never create/replace an output for a failed fetch.
    content = fetch_document(document_id, export_format, opener=opener)
    if output.exists():
        previous = output.read_text(encoding="utf-8")
        timestamp = re.search(r"^\*\*Last synced:\*\* ([^\n]+)$", previous, re.MULTILINE)
        if timestamp and previous == render_report(content, document_id, export_format, timestamp[1]):
            return False  # No timestamp-only weekly commits.
    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    result = render_report(content, document_id, export_format, timestamp)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=output.parent, prefix=".research-sync-", delete=False) as file:
            temporary = Path(file.name)
            file.write(result)
            file.flush()
            os.fsync(file.fileno())
        temporary.chmod(0o644)
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--document-id", default=DOCUMENT_ID)
    parser.add_argument("--format", choices=["md", "txt"], default="md", dest="export_format")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    arguments = parser.parse_args(argv)
    try:
        changed = sync_report(arguments.output, arguments.document_id, arguments.export_format)
    except (SyncError, OSError, ValueError) as error:
        print(f"Research report sync failed: {error}", file=sys.stderr)
        return 1
    print(f"{'Updated' if changed else 'Unchanged'}: {arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

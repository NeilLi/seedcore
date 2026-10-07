"""Read one private Google Doc using local user OAuth; never follow bearer redirects."""
from __future__ import annotations

import json
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener
from http.client import HTTPException

if __package__:
    from . import sync_research_report as public
else:
    import sync_research_report as public

READ_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
DEFAULT_CREDENTIALS = Path.home() / ".config/gcloud/application_default_credentials.json"
DOC_MIME = "application/vnd.google-apps.document"


def access_token(credentials_path: Path) -> str:
    """Refresh in memory. Never print tokens or rewrite the user's credentials."""
    if not credentials_path.is_file():
        raise public.SyncError("Local Google credentials are missing. Complete the private OAuth setup in scripts/docs/README.md.")
    if credentials_path.stat().st_mode & 0o077:
        raise public.SyncError("Google credential file must be readable only by its owner (chmod 600).")
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request as AuthRequest
    except ImportError as error:
        raise public.SyncError("Install scripts/docs/requirements-local.txt in the local agent environment.") from error
    try:
        # Authorized-user credentials only: no service-account key, subprocess,
        # metadata server, or arbitrary credential-provider discovery.
        credentials = Credentials.from_authorized_user_file(str(credentials_path), scopes=[READ_SCOPE])
        transport = AuthRequest()

        def bounded_request(*args, **kwargs):
            kwargs["timeout"] = 30
            return transport(*args, **kwargs)

        credentials.refresh(bounded_request)
        if not credentials.token:
            raise ValueError("No token")
        return credentials.token
    except Exception as error:
        # Auth exceptions may contain sensitive provider responses. Keep logs generic.
        if type(error).__name__ == "TransportError":
            raise public.SyncError("Google OAuth refresh could not reach the provider. Check local network and TLS configuration.") from error
        code = next((item.get("error") for item in error.args if isinstance(item, dict)), None)
        suffix = f" ({code})" if code in {"invalid_grant", "invalid_scope", "invalid_client", "unauthorized_client"} else ""
        raise public.SyncError(f"Local Google OAuth refresh failed{suffix}. Reauthorize with Drive read-only scope; see scripts/docs/README.md.") from error


def fetch_private_document(document_id: str, credentials_path: Path = DEFAULT_CREDENTIALS, *, opener=None, token_provider=access_token):
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,200}", document_id):
        raise public.SyncError("Invalid Google document ID.")
    token = token_provider(credentials_path)
    opener = opener or build_opener(public.NoRedirect())
    base = f"https://www.googleapis.com/drive/v3/files/{document_id}"

    def request(suffix):
        try:
            response = opener.open(Request(base + suffix, headers={"Authorization": f"Bearer {token}"}), timeout=30)
        except HTTPError as error:
            response = error
        except (URLError, OSError, HTTPException) as error:
            raise public.SyncError("Private Drive request failed (network error or timeout).") from error
        if response.status != 200:
            status = response.status
            response.close()
            if status in public.REDIRECTS:
                raise public.SyncError("Private Drive returned a redirect; authorization was not forwarded.")
            if status in (401, 403):
                raise public.SyncError(f"Private Drive HTTP {status}: verify Drive read scope, enabled Drive API, and document access.")
            raise public.SyncError(f"Private Drive request failed with HTTP {status}.")
        return response

    def metadata():
        fields = "id,mimeType,version,modifiedTime,trashed,capabilities(canDownload)"
        with request("?" + urlencode({"fields": fields})) as response:
            try:
                raw = response.read(65537)
                if len(raw) > 65536:
                    raise ValueError("Metadata limit")
                value = json.loads(raw)
                if (value.get("id") != document_id or value.get("mimeType") != DOC_MIME or
                        value.get("trashed") is not False or value.get("capabilities", {}).get("canDownload") is not True or
                        not isinstance(value.get("version"), str) or not value["version"].isdigit() or
                        not isinstance(value.get("modifiedTime"), str)):
                    raise ValueError("Unsupported document metadata")
                return value
            except (ValueError, AttributeError, OSError, HTTPException) as error:
                raise public.SyncError("Source must be an accessible, exportable native Google Doc with valid version metadata.") from error

    before = metadata()
    with request("/export?" + urlencode({"mimeType": "text/markdown"})) as response:
        content = public.read_export(response)
    after = metadata()
    if before != after:
        raise public.SyncError("Google Doc changed during export; candidate was not saved. Retry later.")
    return content, {"document_id": document_id, "version": after["version"], "modified_time": after["modifiedTime"]}

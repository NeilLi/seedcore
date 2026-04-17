#!/usr/bin/env python3
"""
Bootstrap YouTube OAuth credentials for local SeedCore publishing.

This helper performs:
1. OAuth consent URL generation (installed-app style).
2. Local callback capture for authorization code.
3. Code exchange for access + refresh token.
4. Account verification with YouTube Data API.
5. Optional env-file upsert for SeedCore runtime variables.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import threading
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import requests

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
USERINFO_ENDPOINT = "https://www.googleapis.com/oauth2/v2/userinfo"
TOKENINFO_ENDPOINT = "https://oauth2.googleapis.com/tokeninfo"


def _mask_secret(value: str, *, keep_start: int = 4, keep_end: int = 4) -> str:
    if len(value) <= keep_start + keep_end:
        return "*" * len(value)
    return f"{value[:keep_start]}{'*' * (len(value) - keep_start - keep_end)}{value[-keep_end:]}"


def _extract_code_from_redirect(redirect_url: str) -> str:
    parsed = urllib.parse.urlparse(redirect_url.strip())
    query = urllib.parse.parse_qs(parsed.query)
    code = (query.get("code") or [""])[0].strip()
    if not code:
        raise ValueError("No OAuth code found in redirect URL.")
    return code


def _build_auth_url(*, client_id: str, redirect_uri: str, scopes: list[str], state: str) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
    }
    return f"{AUTH_ENDPOINT}?{urllib.parse.urlencode(params)}"


def _exchange_code_for_tokens(
    *,
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    timeout_s: int,
) -> dict[str, Any]:
    response = requests.post(
        TOKEN_ENDPOINT,
        data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=timeout_s,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Token exchange failed: HTTP {response.status_code} {response.text}")
    body = response.json()
    if not str(body.get("access_token") or "").strip():
        raise RuntimeError("Token exchange succeeded but access_token is missing.")
    if not str(body.get("refresh_token") or "").strip():
        raise RuntimeError(
            "Token exchange succeeded but refresh_token is missing. "
            "Re-run and ensure prompt=consent/offline access are approved."
        )
    return body


def _verify_access_token(access_token: str, *, timeout_s: int) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {access_token}"}

    tokeninfo_resp = requests.get(
        TOKENINFO_ENDPOINT,
        params={"access_token": access_token},
        timeout=timeout_s,
    )
    if tokeninfo_resp.status_code >= 400:
        raise RuntimeError(f"OAuth tokeninfo verification failed: HTTP {tokeninfo_resp.status_code} {tokeninfo_resp.text}")
    tokeninfo = tokeninfo_resp.json()
    scope_text = str(tokeninfo.get("scope") or "")
    scopes = [scope.strip() for scope in scope_text.split() if scope.strip()]
    if "https://www.googleapis.com/auth/youtube.upload" not in scopes:
        raise RuntimeError(
            "OAuth token is missing required scope: https://www.googleapis.com/auth/youtube.upload"
        )

    userinfo_resp = requests.get(USERINFO_ENDPOINT, headers=headers, timeout=timeout_s)
    userinfo: dict[str, Any]
    if userinfo_resp.status_code < 400:
        try:
            userinfo = userinfo_resp.json()
        except Exception:
            userinfo = {"raw": userinfo_resp.text}
    else:
        userinfo = {
            "warning": f"userinfo lookup failed: HTTP {userinfo_resp.status_code}",
            "raw": userinfo_resp.text,
        }

    return {
        "channel_id": None,
        "channel_title": None,
        "account_email": userinfo.get("email") if isinstance(userinfo, dict) else None,
        "userinfo": userinfo,
        "tokeninfo": tokeninfo,
    }


def _upsert_env_file(path: Path, values: dict[str, str]) -> None:
    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    keys = set(values.keys())
    output_lines: list[str] = []
    seen: set[str] = set()

    for line in existing:
        stripped = line.strip()
        replaced = False
        for key in keys:
            prefix = f"{key}="
            if stripped.startswith(prefix):
                if key not in seen:
                    output_lines.append(f'{key}="{values[key]}"')
                    seen.add(key)
                replaced = True
                break
        if not replaced:
            output_lines.append(line)

    for key, value in values.items():
        if key not in seen:
            output_lines.append(f'{key}="{value}"')

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(output_lines).rstrip() + "\n", encoding="utf-8")


@dataclass
class CallbackCapture:
    state: str
    code: str | None = None
    error: str | None = None


def _wait_for_code_via_local_callback(
    *,
    redirect_uri: str,
    expected_state: str,
    timeout_s: int,
) -> str | None:
    parsed = urllib.parse.urlparse(redirect_uri)
    if parsed.hostname not in {"127.0.0.1", "localhost"}:
        return None
    if parsed.scheme.lower() != "http":
        return None
    port = parsed.port
    if not port:
        return None
    callback_path = parsed.path or "/"
    capture = CallbackCapture(state=expected_state)

    class OAuthCallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            req = urllib.parse.urlparse(self.path)
            if req.path != callback_path:
                self.send_response(404)
                self.end_headers()
                return
            query = urllib.parse.parse_qs(req.query)
            state = (query.get("state") or [""])[0].strip()
            error = (query.get("error") or [""])[0].strip()
            code = (query.get("code") or [""])[0].strip()
            if state != capture.state:
                capture.error = "OAuth state mismatch."
            elif error:
                capture.error = f"OAuth callback returned error: {error}"
            elif code:
                capture.code = code
            else:
                capture.error = "OAuth callback did not include code."

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            if capture.code:
                message = "<h3>SeedCore OAuth captured. You can close this tab.</h3>"
            else:
                message = (
                    f"<h3>SeedCore OAuth callback received an error.</h3><pre>{capture.error}</pre>"
                )
            self.wfile.write(message.encode("utf-8"))

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

    server = HTTPServer((parsed.hostname, port), OAuthCallbackHandler)
    server.timeout = 0.5

    def run_server() -> None:
        end_ts = time.time() + timeout_s
        while time.time() < end_ts and capture.code is None and capture.error is None:
            server.handle_request()

    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()
    thread.join(timeout=timeout_s + 1)
    server.server_close()

    if capture.error:
        raise RuntimeError(capture.error)
    return capture.code


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap YouTube OAuth for SeedCore local runtime")
    parser.add_argument("--client-id", default=os.getenv("SEEDCORE_YOUTUBE_CLIENT_ID", ""))
    parser.add_argument("--client-secret", default=os.getenv("SEEDCORE_YOUTUBE_CLIENT_SECRET", ""))
    parser.add_argument(
        "--google-client-secret-json",
        default="",
        help="Path to Google OAuth client secrets JSON downloaded from Google Cloud Console.",
    )
    parser.add_argument(
        "--redirect-uri",
        default=os.getenv("SEEDCORE_YOUTUBE_REDIRECT_URI", "http://127.0.0.1:8765/oauth2callback"),
    )
    parser.add_argument(
        "--scopes",
        default="https://www.googleapis.com/auth/youtube.upload openid email profile",
        help="Space-separated OAuth scopes.",
    )
    parser.add_argument("--auth-code", default="", help="Optional pre-captured OAuth code.")
    parser.add_argument(
        "--manual-redirect-url",
        default="",
        help="Optional full redirect URL containing ?code=... when not using local callback server.",
    )
    parser.add_argument(
        "--no-open-browser",
        action="store_true",
        help="Do not auto-open browser; print URL for manual open.",
    )
    parser.add_argument(
        "--no-listen-callback",
        action="store_true",
        help="Disable local callback listener and require --auth-code/--manual-redirect-url input.",
    )
    parser.add_argument("--callback-timeout-s", type=int, default=240)
    parser.add_argument("--http-timeout-s", type=int, default=30)
    parser.add_argument(
        "--env-file",
        default="docker/.env",
        help="Target env file for upsert (used only with --write-env-file).",
    )
    parser.add_argument(
        "--write-env-file",
        action="store_true",
        help="Upsert YouTube OAuth vars into env-file.",
    )
    parser.add_argument(
        "--set-account-email",
        default="",
        help="Optional explicit account email to persist in env as SEEDCORE_YOUTUBE_ACCOUNT_EMAIL.",
    )
    parser.add_argument(
        "--output-json",
        default="",
        help="Optional path for writing non-secret bootstrap summary JSON.",
    )
    args = parser.parse_args()

    client_id = args.client_id.strip()
    client_secret = args.client_secret.strip()
    redirect_uri = args.redirect_uri.strip()

    if args.google_client_secret_json.strip():
        secrets_path = Path(args.google_client_secret_json).expanduser().resolve()
        if not secrets_path.exists():
            raise SystemExit(f"Client secrets JSON not found: {secrets_path}")
        payload = json.loads(secrets_path.read_text(encoding="utf-8"))
        oauth_cfg: dict[str, Any] = {}
        if isinstance(payload, dict):
            if isinstance(payload.get("installed"), dict):
                oauth_cfg = payload["installed"]
            elif isinstance(payload.get("web"), dict):
                oauth_cfg = payload["web"]
        if not oauth_cfg:
            raise SystemExit("Client secrets JSON missing 'installed' or 'web' config block.")

        if not client_id:
            client_id = str(oauth_cfg.get("client_id") or "").strip()
        if not client_secret:
            client_secret = str(oauth_cfg.get("client_secret") or "").strip()
        if args.redirect_uri == parser.get_default("redirect_uri"):
            redirect_uris = oauth_cfg.get("redirect_uris")
            if isinstance(redirect_uris, list):
                for candidate in redirect_uris:
                    candidate_uri = str(candidate or "").strip()
                    if candidate_uri.startswith("http://127.0.0.1:") or candidate_uri.startswith(
                        "http://localhost:"
                    ):
                        redirect_uri = candidate_uri
                        break

    scopes = [scope.strip() for scope in str(args.scopes).split() if scope.strip()]
    if not client_id or not client_secret:
        raise SystemExit(
            "Missing client credentials. Provide --client-id/--client-secret or set "
            "SEEDCORE_YOUTUBE_CLIENT_ID and SEEDCORE_YOUTUBE_CLIENT_SECRET."
        )
    if not redirect_uri:
        raise SystemExit("redirect_uri is required.")
    if not scopes:
        raise SystemExit("At least one scope is required.")

    state = secrets.token_urlsafe(24)
    auth_url = _build_auth_url(client_id=client_id, redirect_uri=redirect_uri, scopes=scopes, state=state)
    print("\n[1/5] OAuth consent URL generated.")
    print(auth_url)

    code = args.auth_code.strip()
    if not code and args.manual_redirect_url.strip():
        code = _extract_code_from_redirect(args.manual_redirect_url)

    if not code:
        callback_code: str | None = None
        if not args.no_listen_callback:
            print(
                f"\n[2/5] Waiting for OAuth callback on {redirect_uri} "
                f"(timeout={args.callback_timeout_s}s)..."
            )
            if not args.no_open_browser:
                webbrowser.open(auth_url)
            else:
                print("Open the URL above in your browser to continue.")
            callback_code = _wait_for_code_via_local_callback(
                redirect_uri=redirect_uri,
                expected_state=state,
                timeout_s=args.callback_timeout_s,
            )
        if callback_code:
            code = callback_code
            print("[2/5] OAuth callback captured successfully.")

    if not code:
        if args.no_open_browser:
            print("\nOpen this URL in your browser to authorize:")
            print(auth_url)
        elif args.no_listen_callback:
            webbrowser.open(auth_url)
        print(
            "\nNo auth code captured automatically. Re-run with either:\n"
            "  --auth-code <code>\n"
            "or\n"
            "  --manual-redirect-url '<full redirect url>'"
        )
        return 2

    print("\n[3/5] Exchanging code for access + refresh token...")
    tokens = _exchange_code_for_tokens(
        code=code,
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        timeout_s=args.http_timeout_s,
    )
    access_token = str(tokens.get("access_token") or "").strip()
    refresh_token = str(tokens.get("refresh_token") or "").strip()
    expires_in = int(tokens.get("expires_in") or 0)

    print("[4/5] Verifying token with YouTube API...")
    verification = _verify_access_token(access_token, timeout_s=args.http_timeout_s)
    account_email = args.set_account_email.strip() or str(verification.get("account_email") or "").strip()

    env_values = {
        "SEEDCORE_YOUTUBE_ACCESS_TOKEN": access_token,
        "SEEDCORE_YOUTUBE_CLIENT_ID": client_id,
        "SEEDCORE_YOUTUBE_CLIENT_SECRET": client_secret,
        "SEEDCORE_YOUTUBE_REFRESH_TOKEN": refresh_token,
    }
    if account_email:
        env_values["SEEDCORE_YOUTUBE_ACCOUNT_EMAIL"] = account_email

    if args.write_env_file:
        env_path = Path(args.env_file).resolve()
        _upsert_env_file(env_path, env_values)
        print(f"[5/5] Updated env file: {env_path}")
    else:
        print("[5/5] Env file update skipped (--write-env-file not set).")

    summary = {
        "status": "ok",
        "expires_in_seconds": expires_in,
        "channel_id": verification.get("channel_id"),
        "channel_title": verification.get("channel_title"),
        "account_email": account_email or None,
        "client_id_masked": _mask_secret(client_id),
        "refresh_token_masked": _mask_secret(refresh_token),
    }
    print("\nBootstrap summary:")
    print(json.dumps(summary, indent=2, sort_keys=True))

    if args.output_json:
        output_path = Path(args.output_json).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"Wrote summary JSON: {output_path}")

    print("\nCurrent-shell exports (optional, immediate use):")
    for key, value in env_values.items():
        print(f'export {key}="{value}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

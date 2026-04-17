#!/usr/bin/env python3
"""
Non-technical YouTube OAuth setup wizard for SeedCore local runtime.

This script guides users through:
1. Collecting/storing client credentials.
2. Launching OAuth consent flow.
3. Persisting refresh/access tokens.
4. Showing plain-language fixes for common OAuth errors.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILE = PROJECT_ROOT / "docker" / ".env"
DEFAULT_SUMMARY_FILE = PROJECT_ROOT / "artifacts" / "demo" / "youtube_oauth_bootstrap.summary.json"
BOOTSTRAP_SCRIPT = PROJECT_ROOT / "scripts" / "host" / "bootstrap_youtube_oauth.py"


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and ((value[0] == '"' and value[-1] == '"') or (value[0] == "'" and value[-1] == "'")):
        return value[1:-1]
    return value


def _load_env_map(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    result: Dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw_value = stripped.split("=", 1)
        key = key.strip()
        if not key:
            continue
        result[key] = _strip_quotes(raw_value)
    return result


def _upsert_env_file(path: Path, values: Dict[str, str]) -> None:
    existing_lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    keys = set(values.keys())
    output_lines = []
    written = set()

    for line in existing_lines:
        stripped = line.strip()
        replaced = False
        for key in keys:
            if stripped.startswith(f"{key}="):
                if key not in written:
                    output_lines.append(f'{key}="{values[key]}"')
                    written.add(key)
                replaced = True
                break
        if not replaced:
            output_lines.append(line)

    for key, value in values.items():
        if key not in written:
            output_lines.append(f'{key}="{value}"')

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(output_lines).rstrip() + "\n", encoding="utf-8")


def _mask(value: str) -> str:
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * (len(value) - 8)}{value[-4:]}"


def _prompt(label: str, default: str = "") -> str:
    if default:
        answer = input(f"{label} [{default}]: ").strip()
        return answer or default
    return input(f"{label}: ").strip()


def _classify_error(output: str) -> Tuple[str, str]:
    text = output.lower()
    if "redirect_uri_mismatch" in text:
        return (
            "Google OAuth redirect URI mismatch.",
            "In Google Cloud -> Credentials -> OAuth client, add both "
            "http://127.0.0.1:8765/oauth2callback and http://localhost:8765/oauth2callback.",
        )
    if "error 403" in text or "access_denied" in text:
        return (
            "Access denied for testing app.",
            "Add your account as a Test user in Google Auth Platform -> Audience, then retry.",
        )
    if "insufficient authentication scopes" in text or "access_token_scope_insufficient" in text:
        return (
            "OAuth token missing required permission scope.",
            "In Google Auth Platform -> Data Access, include youtube.upload scope and retry consent.",
        )
    if "invalid_client" in text:
        return (
            "OAuth client credentials rejected.",
            "Double-check client ID/secret are from the same Google Cloud project and not truncated.",
        )
    if "youtube data api" in text and "permission_denied" in text:
        return (
            "YouTube API access blocked.",
            "Enable YouTube Data API v3 in Google Cloud -> APIs & Services -> Library.",
        )
    return (
        "OAuth setup did not complete.",
        "Check Google Auth Platform settings (Audience test user, Data Access scopes, redirect URIs) and retry.",
    )


def _run_bootstrap(
    *,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    account_email: str,
    env_file: Path,
    output_json: Path,
) -> int:
    cmd = [
        sys.executable,
        str(BOOTSTRAP_SCRIPT),
        "--client-id",
        client_id,
        "--client-secret",
        client_secret,
        "--redirect-uri",
        redirect_uri,
        "--set-account-email",
        account_email,
        "--write-env-file",
        "--env-file",
        str(env_file),
        "--output-json",
        str(output_json),
    ]

    print("\nStarting OAuth consent flow...")
    print("Approve the Google page in your browser, then return here.")
    process = subprocess.Popen(
        cmd,
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    output_lines = []
    assert process.stdout is not None
    for line in process.stdout:
        print(line, end="")
        output_lines.append(line)

    return_code = process.wait()
    all_output = "".join(output_lines)
    if return_code != 0:
        title, fix = _classify_error(all_output)
        print("\nSetup failed.")
        print(f"- Cause: {title}")
        print(f"- Fix: {fix}")
    return return_code


def main() -> int:
    parser = argparse.ArgumentParser(description="Easy YouTube OAuth setup wizard for SeedCore")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE))
    parser.add_argument("--redirect-uri", default="http://127.0.0.1:8765/oauth2callback")
    parser.add_argument("--owner-email", default="lizi.lining@gmail.com")
    parser.add_argument("--client-id", default="")
    parser.add_argument("--client-secret", default="")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--output-json", default=str(DEFAULT_SUMMARY_FILE))
    args = parser.parse_args()

    env_file = Path(args.env_file).expanduser().resolve()
    output_json = Path(args.output_json).expanduser().resolve()
    env_data = _load_env_map(env_file)

    client_id = args.client_id.strip() or env_data.get("SEEDCORE_YOUTUBE_CLIENT_ID", "").strip()
    client_secret = args.client_secret.strip() or env_data.get("SEEDCORE_YOUTUBE_CLIENT_SECRET", "").strip()
    owner_email = args.owner_email.strip() or env_data.get("SEEDCORE_YOUTUBE_ACCOUNT_EMAIL", "").strip()

    print("SeedCore YouTube Easy Setup")
    print(f"- Project root: {PROJECT_ROOT}")
    print(f"- Env file: {env_file}")
    print(f"- Redirect URI: {args.redirect_uri}")

    if not args.non_interactive:
        if not client_id:
            client_id = _prompt("Enter Google OAuth client ID")
        if not client_secret:
            client_secret = _prompt("Enter Google OAuth client secret")
        owner_email = _prompt("YouTube account email", owner_email or "lizi.lining@gmail.com")

    if not client_id or not client_secret:
        print("Missing client ID/secret. Re-run with --client-id and --client-secret, or use interactive mode.")
        return 2

    _upsert_env_file(
        env_file,
        {
            "SEEDCORE_YOUTUBE_CLIENT_ID": client_id,
            "SEEDCORE_YOUTUBE_CLIENT_SECRET": client_secret,
            "SEEDCORE_YOUTUBE_ACCOUNT_EMAIL": owner_email,
        },
    )
    print("\nSaved client credentials into env file.")
    print(f"- Client ID: {_mask(client_id)}")
    print(f"- Client secret: {_mask(client_secret)}")
    print(f"- Account email: {owner_email}")

    rc = _run_bootstrap(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=args.redirect_uri,
        account_email=owner_email,
        env_file=env_file,
        output_json=output_json,
    )
    if rc != 0:
        return rc

    refreshed = _load_env_map(env_file)
    refresh_token = refreshed.get("SEEDCORE_YOUTUBE_REFRESH_TOKEN", "").strip()
    access_token = refreshed.get("SEEDCORE_YOUTUBE_ACCESS_TOKEN", "").strip()
    if not refresh_token or not access_token:
        print("\nSetup finished but token keys were not found in env file. Please re-run setup.")
        return 1

    print("\nAll set.")
    print("- YouTube OAuth tokens are now configured for SeedCore local publishing.")
    print(f"- Summary file: {output_json}")
    print(
        "- Next step: run scripts/host/orchestrate_youtube_publish_pipeline.py "
        "to perform full governed publish flow."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python
"""
YouTube publishing tools for SeedCore.

This module provides a governed external-side-effect tool for uploading videos to
YouTube with optional automatic thumbnail generation.
"""

from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from seedcore.models.governed_mutation import (
    GovernedMutationContract,
    MutationEffectClass,
    MutationReplayMode,
)
from seedcore.tools.base import ToolBase

logger = logging.getLogger(__name__)

_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
_YOUTUBE_UPLOAD_BASE = "https://www.googleapis.com/upload/youtube/v3"


def _utc_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _resolve_access_token(explicit_access_token: Optional[str] = None) -> str:
    token = (explicit_access_token or os.getenv("SEEDCORE_YOUTUBE_ACCESS_TOKEN", "")).strip()
    if token:
        return token

    client_id = os.getenv("SEEDCORE_YOUTUBE_CLIENT_ID", "").strip()
    client_secret = os.getenv("SEEDCORE_YOUTUBE_CLIENT_SECRET", "").strip()
    refresh_token = os.getenv("SEEDCORE_YOUTUBE_REFRESH_TOKEN", "").strip()
    if not client_id or not client_secret or not refresh_token:
        raise ValueError(
            "YouTube OAuth is not configured. Set SEEDCORE_YOUTUBE_ACCESS_TOKEN, "
            "or SEEDCORE_YOUTUBE_CLIENT_ID + SEEDCORE_YOUTUBE_CLIENT_SECRET + "
            "SEEDCORE_YOUTUBE_REFRESH_TOKEN. "
            "Bootstrap locally with scripts/host/bootstrap_youtube_oauth.py --write-env-file."
        )

    resp = requests.post(
        _TOKEN_ENDPOINT,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=20,
    )
    if resp.status_code >= 400:
        raise ValueError(f"OAuth token refresh failed: HTTP {resp.status_code} {resp.text}")
    body = resp.json()
    access_token = str(body.get("access_token") or "").strip()
    if not access_token:
        raise ValueError("OAuth token refresh succeeded but access_token is missing.")
    return access_token


def _initiate_resumable_upload(
    *,
    access_token: str,
    metadata: Dict[str, Any],
    file_size: int,
    content_type: str,
) -> str:
    resp = requests.post(
        f"{_YOUTUBE_UPLOAD_BASE}/videos?uploadType=resumable&part=snippet,status",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Length": str(file_size),
            "X-Upload-Content-Type": content_type,
        },
        json=metadata,
        timeout=30,
    )
    if resp.status_code >= 400:
        raise ValueError(f"YouTube resumable init failed: HTTP {resp.status_code} {resp.text}")
    upload_url = str(resp.headers.get("Location") or "").strip()
    if not upload_url:
        raise ValueError("YouTube resumable init did not return upload Location header.")
    return upload_url


def _upload_video_bytes(
    *,
    upload_url: str,
    access_token: str,
    video_path: Path,
    content_type: str,
) -> Dict[str, Any]:
    file_size = video_path.stat().st_size
    with video_path.open("rb") as fh:
        resp = requests.put(
            upload_url,
            data=fh,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": content_type,
                "Content-Length": str(file_size),
            },
            timeout=600,
        )
    if resp.status_code >= 400:
        raise ValueError(f"YouTube video upload failed: HTTP {resp.status_code} {resp.text}")
    return resp.json()


def _auto_generate_thumbnail(video_path: Path, *, title_hint: str) -> Path | None:
    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        logger.debug("ffmpeg not found, skipping auto thumbnail generation.")
        return None

    output_dir = video_path.parent / ".seedcore_thumbnails"
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_title = "".join(ch.lower() if ch.isalnum() else "-" for ch in title_hint).strip("-")
    safe_title = "-".join(part for part in safe_title.split("-") if part) or "seedcore"
    out_path = output_dir / f"{video_path.stem}-{safe_title}-thumb.jpg"
    cmd = [
        ffmpeg_bin,
        "-y",
        "-ss",
        "00:00:02",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(out_path),
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as exc:
        logger.warning("Failed to auto-generate thumbnail with ffmpeg: %s", exc)
        return None
    return out_path if out_path.exists() else None


def _upload_thumbnail(
    *,
    access_token: str,
    video_id: str,
    thumbnail_path: Path,
) -> Dict[str, Any]:
    with thumbnail_path.open("rb") as fh:
        resp = requests.post(
            f"{_YOUTUBE_UPLOAD_BASE}/thumbnails/set?videoId={video_id}",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "image/jpeg",
            },
            data=fh,
            timeout=120,
        )
    if resp.status_code >= 400:
        raise ValueError(f"YouTube thumbnail upload failed: HTTP {resp.status_code} {resp.text}")
    try:
        return resp.json()
    except Exception:
        return {"raw": resp.text}


class YouTubePublishVideoTool(ToolBase):
    """
    Governed external side-effect tool for publishing videos to YouTube.
    """

    name = "youtube.publish_video"
    description = "Upload and publish a video to YouTube with optional automatic thumbnail generation."

    def governance_contract(self) -> GovernedMutationContract:
        return GovernedMutationContract(
            effect_class=MutationEffectClass.EXTERNAL_SIDE_EFFECT,
            requires_execution_token=False,
            requires_policy_receipt=False,
            requires_signed_receipt=False,
            snapshot_binding_required=False,
            replay_mode=MutationReplayMode.HASH_STABLE,
            notes="External publishing action gated by signed intent and delegated owner authority.",
        )

    async def run(
        self,
        *,
        video_path: str,
        title: str,
        visibility: str = "unlisted",
        audience: str = "kids",
        made_for_kids: Optional[bool] = None,
        description: str = "",
        tags: Optional[List[str]] = None,
        category_id: str = "22",
        account_email: Optional[str] = None,
        thumbnail_mode: str = "ai_auto_generate",
        thumbnail_path: Optional[str] = None,
        notify_subscribers: bool = False,
        access_token: Optional[str] = None,
        **_: Any,
    ) -> Dict[str, Any]:
        visibility_norm = str(visibility or "").strip().lower()
        if visibility_norm not in {"private", "unlisted", "public"}:
            raise ValueError("visibility must be one of: private, unlisted, public")

        audience_norm = str(audience or "").strip().lower()
        if made_for_kids is None:
            made_for_kids = audience_norm == "kids"

        video_file = Path(video_path).expanduser().resolve()
        if not video_file.exists() or not video_file.is_file():
            raise ValueError(f"video_path does not exist or is not a file: {video_file}")

        content_type = mimetypes.guess_type(str(video_file))[0] or "video/mp4"
        video_sha256 = _file_sha256(video_file)
        resolved_access_token = _resolve_access_token(access_token)

        metadata = {
            "snippet": {
                "title": title,
                "description": description or "",
                "tags": [str(tag) for tag in (tags or []) if str(tag).strip()],
                "categoryId": str(category_id),
            },
            "status": {
                "privacyStatus": visibility_norm,
                "selfDeclaredMadeForKids": bool(made_for_kids),
            },
        }
        if notify_subscribers:
            metadata["status"]["notifySubscribers"] = True

        upload_url = _initiate_resumable_upload(
            access_token=resolved_access_token,
            metadata=metadata,
            file_size=video_file.stat().st_size,
            content_type=content_type,
        )
        upload_response = _upload_video_bytes(
            upload_url=upload_url,
            access_token=resolved_access_token,
            video_path=video_file,
            content_type=content_type,
        )
        video_id = str(upload_response.get("id") or "").strip()
        if not video_id:
            raise ValueError("YouTube upload response did not include video ID.")

        thumbnail_payload: Dict[str, Any] | None = None
        thumbnail_source: Path | None = None
        thumb_mode = str(thumbnail_mode or "").strip().lower()
        if thumb_mode != "none":
            if thumbnail_path:
                candidate = Path(thumbnail_path).expanduser().resolve()
                if candidate.exists() and candidate.is_file():
                    thumbnail_source = candidate
            if thumbnail_source is None and thumb_mode in {"ai_auto_generate", "auto_generate", "auto"}:
                thumbnail_source = _auto_generate_thumbnail(video_file, title_hint=title)
            if thumbnail_source is not None:
                thumbnail_payload = _upload_thumbnail(
                    access_token=resolved_access_token,
                    video_id=video_id,
                    thumbnail_path=thumbnail_source,
                )

        publish_record = {
            "status": "published",
            "published_at": _utc_iso(),
            "channel": "youtube",
            "account_email": account_email,
            "video_id": video_id,
            "video_url": f"https://www.youtube.com/watch?v={video_id}",
            "visibility": visibility_norm,
            "made_for_kids": bool(made_for_kids),
            "source_video": {
                "path": str(video_file),
                "sha256": video_sha256,
                "content_type": content_type,
            },
            "request_fingerprint": f"sha256:{hashlib.sha256(_canonical_json(metadata).encode('utf-8')).hexdigest()}",
            "upload_response": upload_response,
            "thumbnail": {
                "mode": thumb_mode or "none",
                "path": str(thumbnail_source) if thumbnail_source is not None else None,
                "response": thumbnail_payload,
            },
        }
        return publish_record

    def schema(self) -> Dict[str, Any]:
        contract = self.governance_contract()
        return {
            "name": self.name,
            "description": self.description,
            "type": "object",
            "properties": {
                "video_path": {"type": "string", "description": "Local path to the video file."},
                "title": {"type": "string", "description": "YouTube video title."},
                "description": {"type": "string", "description": "YouTube video description."},
                "visibility": {
                    "type": "string",
                    "description": "privacy status: private | unlisted | public",
                    "enum": ["private", "unlisted", "public"],
                },
                "audience": {"type": "string", "description": "audience hint, e.g. kids or general."},
                "made_for_kids": {"type": "boolean", "description": "Override made-for-kids flag."},
                "tags": {"type": "array", "items": {"type": "string"}},
                "category_id": {"type": "string", "description": "YouTube category id (default 22)."},
                "account_email": {"type": "string", "description": "Owner YouTube account email."},
                "thumbnail_mode": {
                    "type": "string",
                    "description": "none | ai_auto_generate | auto_generate",
                    "enum": ["none", "ai_auto_generate", "auto_generate"],
                },
                "thumbnail_path": {"type": "string", "description": "Optional path to a thumbnail JPG/PNG."},
                "notify_subscribers": {"type": "boolean"},
            },
            "required": ["video_path", "title"],
            "x_governed_mutation_contract": contract.model_dump(mode="json"),
        }


async def register_youtube_tools(tool_manager: Any) -> bool:
    """
    Register YouTube publishing tools with ToolManager or ToolManagerShard.
    """
    try:
        publish_tool = YouTubePublishVideoTool()
        if hasattr(tool_manager, "register_internal"):
            await tool_manager.register_internal(publish_tool)
        elif hasattr(tool_manager, "register_youtube_tools"):
            result = await tool_manager.register_youtube_tools.remote()
            return bool(result)
        elif hasattr(tool_manager, "register"):
            await tool_manager.register(publish_tool.name, publish_tool)
        else:
            logger.warning("Unknown tool_manager type, cannot register YouTube tools.")
            return False
        logger.info("✅ Registered YouTube tools: youtube.publish_video")
        return True
    except Exception:
        logger.warning("Failed to register YouTube tools", exc_info=True)
        return False

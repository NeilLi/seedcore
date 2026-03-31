from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import Request, urlopen

from .runtime_client import SeedcorePluginError


_YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
    "www.youtu.be",
}


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        output.append(item)
    return output


def _sanitize_external_key(value: str) -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9:_-]+", "-", value).strip("-")
    return sanitized or "external-link"


def _normalize_source_url(source_url: str) -> str:
    value = (source_url or "").strip()
    if not value:
        raise ValueError("source_url is required")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("source_url must be an absolute http(s) URL")
    return value


def _youtube_video_id(parsed) -> str | None:
    host = parsed.netloc.lower()
    path = parsed.path.strip("/")
    if host in {"youtu.be", "www.youtu.be"}:
        candidate = path.split("/", 1)[0]
        return candidate or None
    if host not in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        return None
    if path.startswith("shorts/"):
        parts = path.split("/", 2)
        return parts[1] if len(parts) > 1 and parts[1] else None
    if path == "watch":
        return parse_qs(parsed.query).get("v", [None])[0]
    if path.startswith("embed/"):
        parts = path.split("/", 2)
        return parts[1] if len(parts) > 1 and parts[1] else None
    return None


def _fetch_json(url: str) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "User-Agent": "Seedcore-Gemini-Extension/1.0",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=10.0) as response:
            payload = response.read()
    except Exception as exc:
        raise SeedcorePluginError(f"Failed to fetch public media metadata from {url}: {exc}") from exc
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except Exception as exc:
        raise SeedcorePluginError(f"Public media metadata from {url} was not valid JSON") from exc
    if not isinstance(decoded, dict):
        raise SeedcorePluginError(f"Public media metadata from {url} returned an unexpected payload")
    return decoded


def _youtube_oembed(source_url: str) -> dict[str, Any]:
    oembed_url = f"https://www.youtube.com/oembed?url={quote(source_url, safe='')}&format=json"
    return _fetch_json(oembed_url)


def _extract_hashtags(text: str | None) -> list[str]:
    if not text:
        return []
    hashtags = [match.lower() for match in re.findall(r"#([A-Za-z0-9_]+)", text)]
    return _dedupe(hashtags)


def capture_digital_twin_from_link(
    *,
    source_url: str,
    twin_kind: str = "product",
    subject_name: str | None = None,
) -> dict[str, Any]:
    normalized_source_url = _normalize_source_url(source_url)
    parsed = urlparse(normalized_source_url)
    host = parsed.netloc.lower()
    video_id = _youtube_video_id(parsed)
    captured_at = _utcnow_iso()

    observed_basic_info: dict[str, Any]
    public_media_refs: list[dict[str, Any]]
    authority_source = "public_link"
    provider_name = host
    source_type = "public_link"

    if video_id and host in _YOUTUBE_HOSTS:
        oembed = _youtube_oembed(normalized_source_url)
        source_type = "youtube_short" if "/shorts/" in parsed.path else "youtube_video"
        provider_name = str(oembed.get("provider_name") or "YouTube")
        thumbnail_url = str(oembed.get("thumbnail_url") or "").strip()
        title = str(oembed.get("title") or "").strip()
        author_name = str(oembed.get("author_name") or "").strip()
        author_url = str(oembed.get("author_url") or "").strip()
        authority_source = "youtube_oembed"
        observed_basic_info = {
            "title": title or None,
            "producer_display_name": author_name or None,
            "producer_url": author_url or None,
            "thumbnail_url": thumbnail_url or None,
            "provider_name": provider_name,
            "provider_url": str(oembed.get("provider_url") or "https://www.youtube.com/"),
            "hashtags": _extract_hashtags(title),
        }
        public_media_refs = [
            {
                "url": normalized_source_url,
                "media_type": "video",
                "platform": "youtube",
                "external_id": video_id,
            }
        ]
        if thumbnail_url:
            public_media_refs.append(
                {
                    "url": thumbnail_url,
                    "media_type": "thumbnail_image",
                    "platform": "youtube",
                    "external_id": video_id,
                }
            )
        external_key = f"youtube:{video_id}"
        primary_name = subject_name or title or author_name or external_key
        authority_principal = author_name or None
        authority_principal_url = author_url or None
    else:
        source_stub = _sanitize_external_key(f"{host}{parsed.path or ''}")
        public_media_refs = [
            {
                "url": normalized_source_url,
                "media_type": "link",
                "platform": host,
            }
        ]
        observed_basic_info = {
            "title": subject_name or None,
            "producer_display_name": None,
            "producer_url": None,
            "thumbnail_url": None,
            "provider_name": host,
            "provider_url": f"{parsed.scheme}://{host}",
            "hashtags": [],
        }
        external_key = source_stub
        primary_name = subject_name or source_stub
        authority_principal = None
        authority_principal_url = None

    twin_id = f"external:{_sanitize_external_key(external_key)}"

    return {
        "ok": True,
        "capture_mode": "draft_digital_twin_candidate",
        "captured_at": captured_at,
        "source_url": normalized_source_url,
        "source_type": source_type,
        "platform": "youtube" if video_id and host in _YOUTUBE_HOSTS else host,
        "external_id": video_id,
        "observed_basic_info": observed_basic_info,
        "authority": {
            "status": "external_claim_only",
            "verified": False,
            "authority_source": authority_source,
            "principal_hint": authority_principal,
            "principal_url": authority_principal_url,
            "explanation": (
                "Public link metadata can identify the claimed publisher, but it does not prove "
                "delegated owner authority, certified inspection, or Seedcore trust publication."
            ),
            "required_for_certified_replay": [
                "owner or certifying principal",
                "delegated permit or authority scope",
                "stable twin subject identity",
                "sealed evidence bundle or audit record",
                "signed policy and execution outcome",
            ],
        },
        "digital_twin_candidate": {
            "twin_kind": twin_kind,
            "twin_id": twin_id,
            "display_name": primary_name,
            "lifecycle_state": "observed_external_claim",
            "authority_source": authority_source,
            "source_claim": {
                "provider": provider_name,
                "external_id": video_id,
                "source_url": normalized_source_url,
            },
            "public_media_refs": public_media_refs,
            "observed_facts": {
                "title": observed_basic_info.get("title"),
                "producer_display_name": observed_basic_info.get("producer_display_name"),
                "hashtags": observed_basic_info.get("hashtags"),
            },
        },
        "intent_candidate": {
            "intent_type": "capture_external_production_basics",
            "requested_action": "prepare_digital_twin_candidate",
            "subject_type": twin_kind,
            "subject_id": twin_id,
            "authority_level": "draft_only",
            "evidence_refs": [item["url"] for item in public_media_refs if item.get("url")],
        },
        "next_steps": [
            "Map the observed subject to a real owner, producer, batch, or product twin before asserting authority.",
            "Attach primary production evidence such as lot identity, operator, facility, timestamp, or custody records.",
            "Publish a buyer-facing replay or trust page only after a governed audit record or evidence bundle exists.",
        ],
    }

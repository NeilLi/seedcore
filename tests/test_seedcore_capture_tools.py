from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from seedcore.plugin.capture_tools import capture_digital_twin_from_link


def test_capture_digital_twin_from_youtube_short(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "seedcore.plugin.capture_tools._youtube_oembed",
        lambda source_url: {
            "title": "Risking his life for sweet jungle honey. #honeyhunt #wildhoney #shorts",
            "author_name": "Wild X Mama",
            "author_url": "https://www.youtube.com/@WildxMama",
            "provider_name": "YouTube",
            "provider_url": "https://www.youtube.com/",
            "thumbnail_url": "https://i.ytimg.com/vi/l06uRqnEcn8/hq2.jpg",
        },
    )

    result = capture_digital_twin_from_link(
        source_url="https://www.youtube.com/shorts/l06uRqnEcn8",
        twin_kind="product",
    )

    assert result["ok"] is True
    assert result["platform"] == "youtube"
    assert result["source_type"] == "youtube_short"
    assert result["external_id"] == "l06uRqnEcn8"
    assert result["observed_basic_info"]["producer_display_name"] == "Wild X Mama"
    assert result["observed_basic_info"]["hashtags"] == ["honeyhunt", "wildhoney", "shorts"]
    assert result["authority"]["verified"] is False
    assert result["digital_twin_candidate"]["twin_id"] == "external:youtube:l06uRqnEcn8"


def test_capture_digital_twin_requires_absolute_http_url():
    with pytest.raises(ValueError, match="absolute http"):
        capture_digital_twin_from_link(source_url="youtube.com/watch?v=test")

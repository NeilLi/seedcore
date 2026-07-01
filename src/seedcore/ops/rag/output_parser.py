from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, ConfigDict


class RAGParseError(ValueError):
    def __init__(self, reason_code: str, detail: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {detail}")


class ParsedRAGResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scratchpad: str = ""
    response_body: str


def parse_guarded_rag_response(
    raw_output: str,
    *,
    require_scratchpad: bool = False,
) -> ParsedRAGResponse:
    """
    Parses raw LLM output to extract <scratchpad> reasoning and the <response> body.
    Raises ValueError if tags are malformed or missing.
    """
    scratchpad_content = _extract_single_tag(
        raw_output,
        "scratchpad",
        required=require_scratchpad,
    )
    response_body = _extract_single_tag(raw_output, "response", required=True)
    if response_body is None or not response_body.strip():
        raise RAGParseError("rag_response_empty", "<response> body must be non-empty")

    scratchpad_content = (scratchpad_content or "").strip()
    return ParsedRAGResponse(scratchpad=scratchpad_content, response_body=response_body)


def _extract_single_tag(raw_output: str, tag: str, *, required: bool) -> Optional[str]:
    open_tag = f"<{tag}>"
    close_tag = f"</{tag}>"
    open_count = raw_output.count(open_tag)
    close_count = raw_output.count(close_tag)

    if open_count == 0 and close_count == 0:
        if required:
            raise RAGParseError(f"rag_{tag}_missing", f"{open_tag} tag is required")
        return None
    if open_count != 1 or close_count != 1:
        raise RAGParseError(
            f"rag_{tag}_malformed",
            f"expected exactly one {open_tag} and one {close_tag}",
        )

    pattern = re.compile(
        rf"{re.escape(open_tag)}(?P<body>.*?){re.escape(close_tag)}",
        re.DOTALL,
    )
    match = pattern.search(raw_output)
    if match is None:
        raise RAGParseError(
            f"rag_{tag}_malformed",
            f"{close_tag} must appear after {open_tag}",
        )
    return match.group("body").strip()

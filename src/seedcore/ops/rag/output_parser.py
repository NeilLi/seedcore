from __future__ import annotations

from pydantic import BaseModel, ConfigDict


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
    # 1. Extract scratchpad
    scratchpad_content = ""
    if "<scratchpad>" in raw_output:
        start_idx = raw_output.find("<scratchpad>") + len("<scratchpad>")
        end_idx = raw_output.find("</scratchpad>")
        if end_idx == -1 or end_idx < start_idx:
            raise ValueError("Malformed scratchpad tag structure")
        scratchpad_content = raw_output[start_idx:end_idx].strip()
    elif require_scratchpad:
        raise ValueError("Missing required <scratchpad> tag")

    # 2. Extract response
    if "<response>" not in raw_output:
        raise ValueError("Missing <response> tag")

    start_idx = raw_output.find("<response>") + len("<response>")
    end_idx = raw_output.find("</response>")
    if end_idx == -1 or end_idx < start_idx:
        raise ValueError("Malformed response tag structure")

    response_body = raw_output[start_idx:end_idx].strip()
    return ParsedRAGResponse(scratchpad=scratchpad_content, response_body=response_body)

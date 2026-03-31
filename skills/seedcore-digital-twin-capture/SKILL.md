---
name: seedcore-digital-twin-capture
description: Use when capturing a draft SeedCore digital twin candidate from a public media URL, especially a YouTube link, while keeping authority and certification claims explicit.
---

# Seedcore Digital Twin Capture

Use this skill when the user wants Gemini to turn a public link into a SeedCore-style digital twin draft.

## Preferred MCP flow

1. Call `seedcore.digital_twin.capture_link`.
2. Read the returned `observed_basic_info`, `authority`, and `digital_twin_candidate`.
3. Explain clearly which facts are observed from the public link and which authority or certification fields are still missing.

## Tool-first execution policy

- Execute `seedcore.digital_twin.capture_link` immediately once `source_url` is provided.
- Do not read repository files before the first MCP tool attempt.
- Only inspect docs or code if the MCP call fails, the URL is invalid, or the user asks for implementation details.

## What to report

- The observed source metadata: title, producer/channel, provider, thumbnail, and source URL.
- The draft `digital_twin_candidate` identity and proposed subject type.
- The authority status. Public links are only external claims until SeedCore has a governed audit record or evidence bundle.
- The next steps required to reach a buyer-facing forensic replay or trust page.

## Guardrails

- Do not describe a YouTube link as certified evidence by itself.
- Do not imply delegated owner authority unless the runtime already has a matching governed record.
- If the user wants a `forensic-replay` style page, explain that they still need a certifying principal, a stable twin subject, and a sealed evidence bundle.

## Recommended phrasing

- Say `observed from the public link` for link-derived facts.
- Say `not yet authority-backed` for claims that still need SeedCore governance.
- Say `draft digital twin candidate` rather than `certified twin` unless verification already exists.

# SeedCore Protocol Adoption Plan (2026-03-27)

This document records the phased protocol adoption strategy for SeedCore.
It follows the approved sequence:

1. Keep internal cognition/routing contracts stable.
2. Standardize the external tool boundary on MCP.
3. Keep legacy compatibility during rollout.
4. Expose low-risk MCP tools first.
5. Keep ToolManager as the internal adapter boundary.
6. Defer cross-agent protocol standardization until needed.
7. If external interop is required later, add one gateway (A2A-facing), not a full internal rewrite.

## Step Status

- Step 1 (internal bus remains TaskPayload-based): done.
- Step 2 (MCP boundary standardization): done for client + service boundary.
- Step 3 (MCP lifecycle and transport compliance): done with initialize/session/version headers and compatibility fallback.
- Step 4 (safe-first MCP surface): done (`internet.fetch`, `fs.read` remain the exposed tools).
- Step 5 (adapter pattern): done (`ToolManager` still owns orchestration and only delegates external tools to MCP).
- Step 6 (cross-agent protocol standardization): deferred by design.
- Step 7 (single external agent gateway when needed): deferred by design.

## Current Guardrails

- MCP client now prefers JSON-RPC methods (`tools/list`, `tools/call`) at the MCP endpoint.
- MCP lifecycle is enforced (`initialize` then `notifications/initialized`).
- Streamable HTTP protocol/session headers are propagated:
  - `MCP-Protocol-Version`
  - `MCP-Session-Id`
- MCP service validates `Origin` (when present) with loopback-safe defaults.
- Migration safety remains via opt-out legacy fallback:
  - `MCP_CLIENT_ENABLE_LEGACY_FALLBACK=1` (default)

## Rollout Recommendation

- Keep fallback enabled in early environments.
- Observe tool-call success/error metrics for JSON-RPC path.
- Disable fallback once no consumers depend on legacy `/tools/execute` or `/tools/list`.

# Codex Tool Mapping

This mapping keeps Codex behavior aligned with the Gemini extension tool surface.

## Core parity tools

- `seedcore.health`
- `seedcore.readyz`
- `seedcore.pkg.status`
- `seedcore.pkg.authz_graph_status`
- `seedcore.hotpath.status`
- `seedcore.hotpath.verify_shadow`
- `seedcore.hotpath.benchmark`
- `seedcore.evidence.verify`
- `seedcore.forensic_replay.fetch`
- `seedcore.digital_twin.capture_link`

## Owner / Creator parity tools

- `seedcore.identity.owner.upsert`
- `seedcore.identity.owner.get`
- `seedcore.creator_profile.upsert`
- `seedcore.creator_profile.get`
- `seedcore.delegation.grant`
- `seedcore.delegation.get`
- `seedcore.delegation.revoke`
- `seedcore.trust_preferences.upsert`
- `seedcore.trust_preferences.get`
- `seedcore.owner_context.get`
- `seedcore.owner_context.preflight`
- `seedcore.agent_action.preflight`

## Workflow expectations

- For owner/creator requests, call MCP tools before reading/editing repository files.
- Use `seedcore.owner_context.get` for consolidated provenance-first owner-context reads.
- Use `seedcore.agent_action.preflight` for governed simulation (`no_execute`) before execution paths.

## Fallback when MCP is unavailable

- Use `bash deploy/local/run-api.sh`
- Use `python scripts/host/verify_rct_hot_path_shadow.py`
- Use `python scripts/host/benchmark_rct_hot_path.py --requests 40 --warmup 4 --concurrency 4`

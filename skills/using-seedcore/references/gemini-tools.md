# Gemini Tool Mapping

When Gemini is using the Seedcore extension:

- The extension should start the local `seedcore` MCP server automatically.
- Use `seedcore.health` instead of manually curling `/health`.
- Use `seedcore.readyz` instead of manually curling `/readyz`.
- Use `seedcore.pkg.status` and `seedcore.pkg.authz_graph_status` before discussing PKG readiness.
- Use `seedcore.hotpath.status`, `seedcore.hotpath.metrics` (Prometheus text, read-only), `seedcore.hotpath.verify_shadow`, and `seedcore.hotpath.benchmark` for hot-path promotion analysis.
- Use the Q2 **verification read** tools (all read-only; require the TS verification API on `SEEDCORE_VERIFICATION_API_BASE`, default `http://127.0.0.1:7071`):
  - `seedcore.verification.queue` — transfer queue / Screen 1 data (`GET .../transfers/queue`).
  - `seedcore.verification.transfer_review` — Screen 2 bundle (`GET .../transfers/review`).
  - `seedcore.verification.workflow_projection` — `VerificationSurfaceProjection`.
  - `seedcore.verification.workflow_verification_detail` — Screen 4 detail + failure panel.
  - `seedcore.verification.workflow_replay` — `seedcore.verification_replay.v1` JSON.
  - `seedcore.verification.runbook_lookup` — `seedcore.verification_runbook_lookup.v1` by `reason_code`.
- Use `seedcore.evidence.verify` for trust or replay verification.
- Use `seedcore.forensic_replay.fetch` for public trust-page replay or audit-linked forensic playback.
- Use `seedcore.digital_twin.capture_link` to turn a public media URL into a draft SeedCore digital twin candidate with explicit authority limits.
- For digital-twin capture requests, call `seedcore.digital_twin.capture_link` first and avoid `ReadFile`/`SearchText` unless the MCP call fails.

If the tools are unavailable, treat that as Gemini extension troubleshooting first and only then fall back to:

- `bash deploy/local/run-api.sh`
- `python scripts/host/verify_rct_hot_path_shadow.py`
- `python scripts/host/benchmark_rct_hot_path.py --requests 40 --warmup 4 --concurrency 4`

For Codex parity guidance, see `references/codex-tools.md`.

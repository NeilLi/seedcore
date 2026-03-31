# Gemini Tool Mapping

When Gemini is using the Seedcore extension:

- The extension should start the local `seedcore` MCP server automatically.
- Use `seedcore.health` instead of manually curling `/health`.
- Use `seedcore.readyz` instead of manually curling `/readyz`.
- Use `seedcore.pkg.status` and `seedcore.pkg.authz_graph_status` before discussing PKG readiness.
- Use `seedcore.hotpath.status`, `seedcore.hotpath.verify_shadow`, and `seedcore.hotpath.benchmark` for hot-path promotion analysis.
- Use `seedcore.evidence.verify` for trust or replay verification.
- Use `seedcore.forensic_replay.fetch` for public trust-page replay or audit-linked forensic playback.
- Use `seedcore.digital_twin.capture_link` to turn a public media URL into a draft SeedCore digital twin candidate with explicit authority limits.
- For digital-twin capture requests, call `seedcore.digital_twin.capture_link` first and avoid `ReadFile`/`SearchText` unless the MCP call fails.

If the tools are unavailable, treat that as Gemini extension troubleshooting first and only then fall back to:

- `bash deploy/local/run-api.sh`
- `python scripts/host/verify_rct_hot_path_shadow.py`
- `python scripts/host/benchmark_rct_hot_path.py --requests 40 --warmup 4 --concurrency 4`

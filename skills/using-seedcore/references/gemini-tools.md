# Gemini Tool Mapping

When Gemini is using the Seedcore extension:

- Use `seedcore.health` instead of manually curling `/health`.
- Use `seedcore.readyz` instead of manually curling `/readyz`.
- Use `seedcore.pkg.status` and `seedcore.pkg.authz_graph_status` before discussing PKG readiness.
- Use `seedcore.hotpath.status`, `seedcore.hotpath.verify_shadow`, and `seedcore.hotpath.benchmark` for hot-path promotion analysis.
- Use `seedcore.evidence.verify` for trust or replay verification.

If the MCP server is unavailable, fall back to:

- `bash deploy/local/run-api.sh`
- `python scripts/host/verify_rct_hot_path_shadow.py`
- `python scripts/host/benchmark_rct_hot_path.py --requests 40 --warmup 4 --concurrency 4`

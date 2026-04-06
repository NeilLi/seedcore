# Gemini Q2 Verification Acceptance Check

Use this prompt when you need to verify the SeedCore Q2 read-only verification surface without retrying live-only runtime evidence checks.

```text
Run the SeedCore MCP acceptance check with fixture-backed Q2 verification only.

Acceptance checklist:
1. **Minimal Gemini-visible read bundle** (frozen contract proxies only; see `GET /info` → `gemini_minimal_read_only_bundle` on the plugin MCP app):
   - seedcore.verification.queue
   - seedcore.verification.workflow_verification_detail
   - seedcore.verification.workflow_replay
   - seedcore.verification.runbook_lookup
   - seedcore.hotpath.status (`read_only`, full status under `data`, including `observability` / `alert_level`)
   - seedcore.hotpath.metrics
2. Optional extra verification/hot-path tools (still read-only, not in the minimal bundle):
   - seedcore.verification.transfer_review
   - seedcore.verification.workflow_projection

3. Verify the minimal-bundle tools and mark PASS only if they are read-only shaped and return expected payloads (for the items in section 1).

4. For the verification tools, use the allow_case fixture family and capture:
   - workflow_id
   - audit_id
   - intent_id
   - subject_id

5. For hotpath.status, report (from `data` and top-level summary fields):
   - mode
   - parity summary
   - enforce_ready
   - graph_freshness_ok
   - alert level if present

6. For hotpath.metrics, confirm:
   - Prometheus text is reachable
   - output includes alert/rollback or parity-related metrics

7. Skip these tools unless you have a real runtime audit/public ID:
   - seedcore.evidence.verify
   - seedcore.forensic_replay.fetch

8. If only fixture IDs are available, mark the two live-only tools as SKIPPED with reason:
   - live-only runtime ID required
   - blocked-by-data

Output format:
- a compact table with columns:
  tool_name | status | reason | source_url
- a separate “Captured fixture IDs” section
- a final verdict:
  READY if all fixture-backed tools pass and live-only tools are correctly skipped
  otherwise NOT_READY
```

Related tool map:

- [Gemini Tool Mapping](gemini-tools.md)

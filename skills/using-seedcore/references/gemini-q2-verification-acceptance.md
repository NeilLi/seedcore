# Gemini Q2 Verification Acceptance Check

Use this prompt when you need to verify the SeedCore Q2 read-only verification surface without retrying live-only runtime evidence checks.

```text
Run the SeedCore MCP acceptance check with fixture-backed Q2 verification only.

Acceptance checklist:
1. Verify these tools and mark PASS only if they are read-only shaped and return expected payloads:
   - seedcore.verification.queue
   - seedcore.verification.transfer_review
   - seedcore.verification.workflow_projection
   - seedcore.verification.workflow_verification_detail
   - seedcore.verification.workflow_replay
   - seedcore.verification.runbook_lookup
   - seedcore.hotpath.status
   - seedcore.hotpath.metrics

2. For the verification tools, use the allow_case fixture family and capture:
   - workflow_id
   - audit_id
   - intent_id
   - subject_id

3. For hotpath.status, report:
   - mode
   - parity summary
   - enforce_ready
   - graph_freshness_ok
   - alert level if present

4. For hotpath.metrics, confirm:
   - Prometheus text is reachable
   - output includes alert/rollback or parity-related metrics

5. Skip these tools unless you have a real runtime audit/public ID:
   - seedcore.evidence.verify
   - seedcore.forensic_replay.fetch

6. If only fixture IDs are available, mark the two live-only tools as SKIPPED with reason:
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

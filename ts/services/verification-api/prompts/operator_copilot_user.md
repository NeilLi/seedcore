Using only CONTEXT_JSON, produce the operator copilot brief JSON.

Include these top-level keys with appropriate values:
`contract_version`, `generation_mode` ("llm"), `case_id`, `decision`, `current_status`, `why`, `evidence_completeness`, `verification_status`, `anomalies` (array), `recommended_action`, `audit_note`, `confidence`, `uncertainty_notes` (array, required), `one_line_summary`, `operator_brief_bullets`, `facts`, `inferences`, `citations` (array of {path,value}).

Set `case_id` to CONTEXT_JSON.workflow_id exactly.

# Agent And Protocol Integrations

Date: 2026-10-20
Status: Supporting interfaces and research

Reuse these ingress and capability interfaces when connecting an agent to the
Microduck workflow. They carry requests and context; admission remains with
the PDP and execution boundary. Exact upstream robot RPC translation belongs
in the Microduck adapter plan.

The [robotics partner integration design](robotics_partner_integration_architecture.md)
extends this boundary to candidate compute, sensor, middleware and behavior
providers. It is a proposal with read-only/offline entry points; no partner
adapter or physical qualification is established.

## Remote LLM Accounts + Local AI Station Boundary

A builder may use an optional remote LLM to propose designs or tasks while
running authoring and verification on a local development computer:

- **Proposal boundary:** candidate `seedcore.assembly.v2` JSON can be imported through the existing raw-text validation path. A remote model must not receive signing keys or direct motor access; a general provider-to-studio integration is not implied.
- **Authoring boundary:** strict parsing, catalog byte pins and semantic checks precede acceptance into the store. DRC then reports `pass`, `blocked` or `conflict`; blocked drafts remain usable for offline authoring.
- **Execution boundary:** governed live attempts require the accountable Agent, PDP, scoped token and qualified executor. Session Lab currently uses an explicit simulation issuer, and standalone physics lessons do not invoke the production PDP. The assembly-to-simulation handoff remains planned.

## Documents

- [Robotics partner integration architecture](robotics_partner_integration_architecture.md)
- [Agent Capability & Skills Quick Reference](agent_capability_skills_quick_reference.md)
- [Agent Capability and Skills Relationships Summary](agent_capability_skills_relationships.md)
- [AP2 And SeedCore RCT Alignment Memo](ap2_seedcore_rct_alignment_memo.md)
- [Baseline Task Types Analysis](baseline_task_types_analysis.md)
- [Gemini Owner/Creator Phase 1-3 Quickstart](gemini_phase1_quickstart.md)
- [Delegated Intent Over Kafka](kafka_delegated_intent_ingress.md)
- [Schedule: Local Kafka microservice for intent, telemetry, and policy outcomes](local_kafka_streams_schedule.md)
- [Design: External SDK, Plugin, and Skills Surface for the Owner / Creator Layer](owner_creator_external_sdk_and_plugin_surface.md)
- [Source Registration Tracking Event Curl Collection](source_registration_tracking_event_curl_collection.md)
- [Source Registration Tracking Event Sequence](source_registration_tracking_event_sequence.md)

Return to the [development map](../README.md).

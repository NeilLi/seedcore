# Development Reports

This directory contains dated test analyses and engineering reports that
support development decisions. Reports are evidence or working references;
they do not change implementation status, acceptance criteria, or the active
queue by themselves.

For reproducible test results, include the command, environment, source
revision, date, outcome, and relevant limitations. Mark supplied or
unverified material clearly, and link to the owning plan or contract when one
exists.

## Reports

- [Embodied AI Research Report](embodied_ai_research_report.md) — external literature, model and mini robotics reference. Synchronized on 2026-10-12 from [Google Doc `1bmNZjWUA6_rjFAl2_VT27XZO_9zCU9EpirFXEJM7YNU`](https://docs.google.com/document/d/1bmNZjWUA6_rjFAl2_VT27XZO_9zCU9EpirFXEJM7YNU/edit) via `scripts/docs/sync_research_report.py` (SHA-256: `ae298aacda731e6a96b7becc09502a60bbae936adfe07ac532aea213ea6d7dc9`). Source claims remain unverified external evidence.
  - **Reviewed interpretation:** Read the [architecture reference](../robotics/embodied_ai_architecture_reference.md) for corrections and proposed integration guidance. The archived source remains verbatim; its digest establishes content integrity, not scientific validation.
  - **Timing:** Planning, policy inference and native control have separate deadlines. The report's frequency ranges and 20 ms allocation are illustrative; action execution rate does not establish fresh inference rate or SeedCore performance.
  - **Policy selection:** ACT, diffusion, flow matching and tokenized policies are candidates for measured comparison. Continuous outputs alone do not guarantee jerk bounds, stability or collision avoidance.
  - **Local limits:** Force/pressure limits, stop behavior and response times require robot- and task-specific review and measurements. The report's generic force pair and cutoff claims do not establish ISO compliance or implemented HAL behavior.
  - **SeedCore integration:** Keep admission outside local control while enforcing session expiry, command binding/freshness and revocation freshness locally. The Microduck adapter and hardware acceptance remain planned; automated reward synthesis is a research extension.
- [Microduck Simulation and Architecture Report](microduck_simulation_architecture_report.md) — supplied draft; describes the companion Microduck and `microduck_rl` projects and has not been independently verified.

Return to the [development map](../README.md).

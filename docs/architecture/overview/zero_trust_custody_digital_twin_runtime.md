# SeedCore Architecture: Zero-Trust Custody and Digital-Twin Runtime

This document presents an investor-ready view of how AI assistants, creators, cloud platforms, and physical systems interact through SeedCore's zero-trust custody and digital-twin runtime.

## Diagram

```mermaid
flowchart TB
    AI["AI Ecosystem<br/>- OpenAI Assistants<br/>- Google AI Agents<br/>- Personal AI (OpenClaw, etc.)<br/>- Autonomous Workflows"]
    OWNER["Owner / Creator Layer<br/>- Owner identity<br/>- Creator profiles<br/>- Assistant delegations<br/>- Trust preferences"]

    subgraph RUNTIME["SeedCore Zero-Trust Runtime"]
        PDP["Policy Decision Engine (PDP)<br/>- Authority validation<br/>- Risk policies<br/>- Commerce trust rules<br/>- Publishing policies"]
        ETS["Execution Token Service<br/>- Short-lived action tokens<br/>- Assistant authorization<br/>- Endpoint gating"]
        DTE["Digital Twin Engine<br/>Maintains twins for:<br/>- Owners<br/>- AI assistants<br/>- Assets / batches<br/>- Products<br/>- Edge devices<br/>- Transactions"]
        CG["Custody Graph<br/>Tracks:<br/>- who had it<br/>- where it was<br/>- when it changed<br/>- policy + evidence"]
        ER["Evidence and Replay Layer<br/>- Signed receipts<br/>- Event logs<br/>- Forensic replay<br/>- Trust pages"]
    end

    CLOUD["Cloud and Platform APIs<br/>- AWS / Alibaba<br/>- Commerce platforms<br/>- Creator platforms<br/>- Marketplaces"]
    EDGE["Edge / Physical Layer<br/>Edge Trust Nodes:<br/>- Cameras<br/>- RFID / QR scanners<br/>- Weight sensors<br/>- Storage locks"]
    PUBLISH["Publish Surface<br/>- Creator content<br/>- Product listings<br/>- Batch releases"]
    COMMERCE["Commerce Surface<br/>- Trusted products<br/>- AI purchases<br/>- Provenance goods"]

    AI -->|"Delegated intent"| OWNER
    OWNER -->|"Intent + authority"| PDP
    PDP --> ETS
    ETS --> DTE
    DTE --> CG
    CG --> ER
    ER --> CLOUD
    ER --> EDGE
    CLOUD --> PUBLISH
    EDGE --> COMMERCE
```

## How To Read The Diagram

### Top Layer: AI Assistants

Represents the agentic future across proprietary and open ecosystems. Assistants generate intents (publish, list, buy, unlock, release, move custody) but do not execute directly. All execution must pass through SeedCore governance.

### Owner / Creator Layer

Each owner has a digital twin that defines delegated permissions, purchase policies, publishing authority, risk thresholds, and custody preferences. Assistants can only act inside this delegated authority.

### SeedCore Zero-Trust Runtime

This is the trust and execution control core:

- `Policy Decision Engine (PDP)`: evaluates authority, trust level, provenance requirements, commerce rules, and custody conditions.
- PDP decision semantics: final authorization is synchronous and stateless at decision time over pinned policy/context inputs; approval/custody/telemetry state and replay evidence are managed by surrounding runtime services.
- `Execution Token Service`: issues short-lived execution tokens when policy passes; endpoints reject unauthorized calls.
- `Digital Twin Engine`: keeps governed state for owners, assistants, products, batches, edge nodes, transactions, and assets.
- `Custody Graph`: records ownership, storage, transfer, release, and handling transitions for provenance and disputes.
- `Evidence and Replay Layer`: produces signed, timestamped, replayable evidence for auditability and trust transparency.

### Cloud Platform Layer

SeedCore integrates with cloud providers, commerce systems, creator platforms, and marketplaces. It acts as a trust layer between AI decisions and platform execution.

### Edge / Physical Layer

Optional edge trust nodes add hardware-rooted trust signals (camera, RFID/QR, weight, lock, and related telemetry) to bind digital decisions to real-world state.

### Publish Surface

Creators release verified content, batch products, trust pages, and provenance-backed listings.

### Commerce Surface

AI assistants can purchase on behalf of owners under policy guardrails, with trusted merchants, provenance checks, and replayable transactions.

## Strategic Message

SeedCore is the zero-trust runtime that allows AI assistants to safely publish, transact, and operate in the real world with provable authority and custody.

## Implementation Companion

For an implementation-oriented mapping of the Owner / Creator layer as a Gemini extension, see:

- [Gemini Extension: Owner / Creator Layer Implementation](./gemini_owner_creator_extension.md)
- [Sequence Of Trust: Zero-Trust Physical Custody](./sequence_of_trust_zero_trust_physical_custody.md)

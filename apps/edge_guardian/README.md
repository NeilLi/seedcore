SeedCore Edge Guardian
A Cognitive Coordination Layer for Autonomous Smart Hotels
Hackathon Track: Tuya × AWS
Hardware: Tuya T5 AI Dev Board
Cloud Stack: AWS (EKS, IoT Core, DynamoDB, Ray)
Scenario Focus: Smart Hotel Operations
Core Innovation: Unified State + Energy-Guided Intelligence
1. Inspiration
Modern hotels are rapidly becoming autonomous environments. A single hotel now operates with:
Hundreds of smart locks, cameras, lights, and HVAC units
Service robots and automated cleaning systems
AI concierges and cloud-based management software
Guests, staff, vendors, and delivery services—all with time-bound access
The challenge is no longer connecting devices; it is coordinating behavior across many entities—often with minimal human supervision.
Today’s hotel automation is still rule-based and device-centric:
Each system reacts independently
Context is fragmented across vendors
False alerts disrupt guests and staff
Privacy and accountability are hard to manage
SeedCore Edge Guardian was built to solve this coordination problem at the system level.
2. What SeedCore Does (Uniquely)
SeedCore Edge Guardian is not a traditional security system and not a rule engine. It is a cognitive coordination layer that:
Consolidates signals from hotel devices into a Unified State
Reasons across guests, staff, robots, rooms, and zones
Uses an Energy Function to decide how much intelligence is needed
Produces explainable, system-level decisions, not raw alerts
Instead of asking, “Did a sensor trigger?” SeedCore asks, “What is happening in the hotel right now, and how should the system respond?”
3. Core SeedCore Concepts (Hotel-Relevant)
Unified State (SeedCore-Specific)
SeedCore maintains a hotel-wide state combining:
Guest check-in / check-out status
Staff roles and shift schedules
Robot assignments and locations
Room states and zone permissions
Time, mode, and recent activity
This allows decisions to be made at the hotel level, not per device.
Energy-Guided Intelligence
SeedCore computes an internal energy score based on:
Novelty (is this unusual for this zone and role?)
Uncertainty
Cost and latency sensitivity
Low-energy situations stay on the fast execution path. High-energy situations escalate to deeper cloud reasoning. This keeps the system:
Responsive
Cost-controlled
Privacy-aware
Task Graphs & Organ Graphs
Task-level graphs: model workflows like “entry handling” or “room access”
Organ-level graphs: represent persistent responsibilities (lobby monitoring, corridor access, housekeeping coordination)
This makes the system extensible without rewriting logic.
4. Flagship Demo Scenario — Smart Hotel Night Shift
Scenario: “Is This Activity Normal?”
Environment
Tuya T5 devices in the lobby and corridor
Smart door locks
Lighting and notification systems
Cloud-based hotel management system
Step 1: Edge Detection (Tuya T5)
At 23:40, a Tuya T5 camera detects a person entering a staff-only corridor. The edge device:
Performs lightweight inference (“person detected”)
Generates a structured event with an anomaly score
Does not make a decision
{
 "event_type": "person_detected",
 "zone": "staff_corridor",
 "timestamp": "23:40",
 "anomaly_score": 0.81
}
Step 2: Unified State Reasoning (AWS Cloud Cortex)
SeedCore evaluates the event using hotel-wide context:
Time: late night
Zone: staff-only
Staff schedule: one cleaner on duty
Robot activity: cleaning robot active on the same floor
Guest status: no guest access allowed
The Control Plane computes high novelty → escalates reasoning.
Step 3: Explainable Decision
SeedCore produces an explanation:
“Unrecognized person detected in staff-only corridor outside scheduled access. No matching staff role or robot assignment found.” This explanation is logged and visible to operators.
Step 4: Coordinated Action (Tuya DP Updates)
SeedCore issues coordinated actions:
Turn on corridor lights
Lock adjacent service doors
Notify night staff quietly via the dashboard
No alarms. No guest disturbance. Just coordinated intelligence.
5. Why Tuya + AWS Is Essential
Tuya
Real-world edge hardware (T5) suitable for hotels
Fast integration with locks, lighting, HVAC
DP-based control for coordinated actions
AWS
Kubernetes (EKS) for scalable coordination
Ray for distributed tasks and reasoning
IoT Core for secure messaging
DynamoDB for unified state and audit trails
Tuya provides perception and actuation. AWS provides system-level cognition.
6. Why This Is Different (Judge Summary)
7. Hackathon Roadmap
Phase 1: Cloud simulation with unified state and explanations
Phase 2: Tuya T5 live hotel corridor demo
Phase 3: Energy routing + operator dashboard
Each phase is independently demoable.
8. Market & Future Expansion
The same coordination layer extends naturally to:
Smart apartments
Autonomous hotels
Mixed-use buildings
Smart campuses
Hotels are the ideal starting point because they expose the full coordination problem.
9. Closing Statement
SeedCore Edge Guardian demonstrates how Tuya edge intelligence and AWS cloud scalability can work together to enable autonomous hotels that understand situations, not just sensors. SeedCore doesn’t add more rules. It adds coordinated intelligence.



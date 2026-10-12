# SeedCore v2.5+ VLA Configuration - 2026 Optimizations

Review scope (2026-10-12): The embodied AI update below qualifies timing and
policy-selection guidance only. Earlier configuration and implementation claims
in this document have not been revalidated by that review. For current robotics
status and authority boundaries, use the [active queue](../current_next_steps.md)
and [robot execution contract](robot_execution_contract.md).

## Review Summary

The SeedCore v2.5+ VLA configuration has been reviewed and optimized based on 2026 robotics best practices and the latest VLA breakthroughs.

## ✅ Implemented Optimizations

### 1. Enhanced Safety Layer (2026 Best Practice)

**Added Safety Guard Agent**:
- Dedicated `safety_guard` specialization for red-teaming
- High-frequency monitoring (0.1s interval)
- E-STOP coordination with Generalist

**Enhanced Safety Check Behavior**:
- `safety_level` extraction from `params.risk` for E-STOP triggers
- Joint limit validation to detect hallucinated motor coordinates
- Guardrail model integration (Llama-Guard-3-Robot)
- Remote LLM escalation for high-risk actions

**Configuration**:
```yaml
safety_check:
  enabled: true
  guardrail_enabled: true
  guardrail_model: "meta-llama/Llama-Guard-3-Robot"
  risk_threshold: 0.8
  joint_limit_check: true
  safety_level_estop: 0.95  # E-STOP if safety_level >= 0.95
```

### 2. 3D Geometric Awareness (2026 Standard)

**Added Skill**:
- `3d_geometric_awareness: 0.9` to `reachy_actuator` specialization
- Supports point cloud and depth data (GeoVLA, 4D-VLA models)

**Note**: Models like GeoVLA and 4D-VLA (standardized in late 2025) now use point clouds rather than just 2D video. The actuator is ready to consume depth data.

### 3. NVIDIA GR00T 1.6 Integration (2026 CES Update)

**Added Tool**:
- `isaac.gym.validate_action` to `reachy_actuator` allowed_tools
- Enables sim-run validation before physical execution
- Reduces wear and tear on Reachy Mini

**Sim-to-Real Validation Loop**:
- Added topology bond: `reachy_actuator` ↔ `isaac.gym` (weight: 0.85)
- All motor commands validated in virtual Reachy Mini instance before execution

### 4. Enhanced Topology Bonds

**New Bonds**:
- `reachy_actuator` ↔ `safety_guard` (0.95): Red-Teaming bond
- `reachy_actuator` ↔ `isaac.gym` (0.85): Sim-to-Real validation
- `safety_guard` ↔ `GENERALIST` (0.75): E-STOP coordination

**Updated Bonds**:
- Discovery → Distillation (0.75): Ensures new VLA models trigger training pipeline
- Distillation → Execution (0.7): Model swap event triggers inference engine reload

### 5. GPT-5 Support (2026 Frontier Reasoning)

**Added Tool**:
- `teacher.escalate_gpt5` to `distill_expert` for frontier reasoning tasks
- GPT-5 is the 2026 standard for complex reasoning (replaces GPT-4o for high-risk tasks)

## Architecture Highlights

### Safety Flow (2026)
```
VLA Model Output → Safety Guard → Joint Limit Check → Guardrail Model
                                                      ↓
                                              safety_level >= 0.95?
                                                      ↓
                                              E-STOP (immediate)
```

### Sim-to-Real Flow (2026)
```
Tool Call → isaac.gym.validate_action → Virtual Reachy Mini
                                          ↓
                                    Valid?
                                          ↓
                                    Physical Execution
```

### Risk Escalation Flow
```
Local Brain → Guardrail (risk >= 0.8) → Remote LLM (GPT-5/Claude-4)
                                        ↓
                                    Final Decision
```

## Performance Notes

### Proprioception Sync Interval
- **Earlier configuration note:** 0.2s (5 Hz) describes the documented high-level sync interval; it does not establish a measured native motor or policy-inference rate.
- **Illustrative 50 Hz action target:** A 50 Hz period is 20 ms. The [architecture reference](embodied_ai_architecture_reference.md#2-timing-budgets-require-a-measured-profile) preserves the source's example allocation and its qualification requirements; it is not a SeedCore throughput guarantee or a universal requirement for fluid motion.
- **Separate timing measurements:** Record sensor cadence, observation age, complete inference latency, chunk refresh, action execution and native control independently. Original π0 reports 73 ms onboard inference and refreshes chunks every 0.5 seconds for its 50 Hz robots ([paper, Appendix A-D](https://arxiv.org/html/2410.24164v1)).
- **Policy choice:** Compare ACT, diffusion, flow matching and tokenized policies on the selected body and task. Continuous outputs do not guarantee jerk limits or stability; trajectory constraints need explicit validation. Start the Microduck integration with a compatible pinned upstream policy.
- **Local authority:** Admission stays outside the motor loop. Cached session authority still requires local expiry/duration, command binding/sequence/freshness and revocation-freshness enforcement; refer to the [session contract](robot_execution_contract.md#session-lifecycle-and-time).

### Model Discovery Interval
- **Current**: 30s - Well-timed for 2026 HF LeRobot registry frequency
- **Optimal**: Balances discovery speed vs. resource usage

## Task Payload Risk Structure (2026)

```jsonc
{
  "params": {
    "risk": {
      "level": 0.8,           // Overall risk (0-1)
      "safety_level": 0.92,   // 2026: E-STOP trigger (0-1)
      "is_high_stakes": true,
      "reason": "New model calibration"
    }
  }
}
```

**E-STOP Logic**:
- If `safety_level >= safety_level_estop` (default: 0.95) → Immediate E-STOP
- If `risk.level >= risk_threshold` (default: 0.8) → Escalate to remote LLM
- Joint limit violations → Block action immediately

## Next Steps

1. **Implement Isaac Gym Integration**: Create `isaac.gym.validate_action` tool
2. **Point Cloud Support**: Add depth data processing to `reachy_actuator`
3. **Performance Tuning**: Qualify separate sensor, inference, action and native-control timing for the selected profile before adopting a frequency target
4. **GPT-5 Integration**: Update Teacher escalation to use GPT-5 for frontier tasks

## References

- NVIDIA GR00T 1.6: Open-sourced at CES 2026, integrated into LeRobot
- GeoVLA / 4D-VLA: Point cloud-based VLA models (late 2025 standard)
- Llama-Guard-3-Robot: Meta's safety guardrail model for robotics
- Physical Intelligence π0: [Original model and inference measurements](https://arxiv.org/html/2410.24164v1); distinguish action frequency from chunk refresh
- Embodied AI Architecture Reference: [`embodied_ai_architecture_reference.md`](embodied_ai_architecture_reference.md)
- Embodied AI Research Report: [`../reports/embodied_ai_research_report.md`](../reports/embodied_ai_research_report.md)

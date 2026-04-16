from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class MutationEffectClass(str, Enum):
    READ_ONLY = "read_only"
    PHYSICAL_ACTUATION = "physical_actuation"
    DIGITAL_STATE = "digital_state"
    IDENTITY_STATE = "identity_state"
    TRACKING_STATE = "tracking_state"
    FINANCIAL_STATE = "financial_state"
    EXTERNAL_SIDE_EFFECT = "external_side_effect"


class MutationReplayMode(str, Enum):
    NONE = "none"
    HASH_STABLE = "hash_stable"
    BYTE_STABLE = "byte_stable"


class GovernedMutationContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    effect_class: MutationEffectClass = Field(
        description="Classifies the mutation effect for governance policy."
    )
    requires_execution_token: bool = Field(default=False)
    requires_policy_receipt: bool = Field(default=False)
    requires_signed_receipt: bool = Field(default=False)
    snapshot_binding_required: bool = Field(default=False)
    replay_mode: MutationReplayMode = Field(default=MutationReplayMode.NONE)
    notes: Optional[str] = None

    def is_mutating(self) -> bool:
        return self.effect_class != MutationEffectClass.READ_ONLY

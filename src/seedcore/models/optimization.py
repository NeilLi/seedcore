from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


OptimizerBackend = Literal["none", "fixture", "cuopt"]
RoutePlanValidationDisposition = Literal["allow", "deny", "quarantine"]


class RoutePlanAuthorityWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    starts_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def _expires_after_start(self) -> "RoutePlanAuthorityWindow":
        if self.expires_at <= self.starts_at:
            raise ValueError("expires_at must be after starts_at")
        return self


class RoutePlanStop(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stop_id: str
    sequence: int = Field(ge=0)
    location_ref: str
    zone_ref: Optional[str] = None
    actor_ref: Optional[str] = None
    device_ref: Optional[str] = None
    asset_refs: List[str] = Field(default_factory=list)
    planned_arrival_at: Optional[datetime] = None
    planned_departure_at: Optional[datetime] = None


class RoutePlanProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: str
    workflow_join_key: str
    optimizer_backend: OptimizerBackend
    generated_at: datetime
    route_plan_hash: Optional[str] = None
    asset_refs: List[str] = Field(default_factory=list)
    actor_refs: List[str] = Field(default_factory=list)
    device_refs: List[str] = Field(default_factory=list)
    origin_ref: str
    destination_ref: str
    stops: List[RoutePlanStop] = Field(default_factory=list)
    authority_window: Optional[RoutePlanAuthorityWindow] = None
    policy_snapshot_ref: Optional[str] = None
    constraints_hash: Optional[str] = None


class RoutePlanValidationContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_join_key: str
    allowed_asset_refs: List[str] = Field(default_factory=list)
    allowed_actor_refs: List[str] = Field(default_factory=list)
    allowed_device_refs: List[str] = Field(default_factory=list)
    origin_ref: str
    destination_ref: str
    authority_window: RoutePlanAuthorityWindow
    forbidden_zone_refs: List[str] = Field(default_factory=list)
    quarantined_asset_refs: List[str] = Field(default_factory=list)
    policy_snapshot_ref: Optional[str] = None


class RoutePlanPostValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: str
    route_plan_hash: Optional[str] = None
    disposition: RoutePlanValidationDisposition
    reason_codes: List[str] = Field(default_factory=list)
    policy_snapshot_ref: Optional[str] = None
    authority_minted: Literal[False] = False

    @model_validator(mode="after")
    def _non_allow_has_reasons(self) -> "RoutePlanPostValidationResult":
        if self.disposition != "allow" and not self.reason_codes:
            raise ValueError("deny and quarantine validation results require reason_codes")
        return self

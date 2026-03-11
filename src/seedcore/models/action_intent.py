from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field  # pyright: ignore[reportMissingImports]


class SecurityContract(BaseModel):
    hash: str
    version: str


class IntentPrincipal(BaseModel):
    agent_id: str
    role_profile: str
    session_token: str


class IntentAction(BaseModel):
    type: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    security_contract: SecurityContract


class IntentResource(BaseModel):
    asset_id: str
    target_zone: Optional[str] = None
    provenance_hash: str
    source_registration_id: Optional[str] = None
    registration_decision_id: Optional[str] = None


class ActionIntent(BaseModel):
    intent_id: str
    timestamp: str
    valid_until: str
    principal: IntentPrincipal
    action: IntentAction
    resource: IntentResource


class ExecutionToken(BaseModel):
    token_id: str
    intent_id: str
    issued_at: str
    valid_until: str
    contract_version: str
    signature: str
    constraints: Dict[str, Any] = Field(default_factory=dict)


class PolicyDecision(BaseModel):
    allowed: bool
    execution_token: Optional[ExecutionToken] = None
    reason: Optional[str] = None
    policy_snapshot: Optional[str] = None
    deny_code: Optional[str] = None

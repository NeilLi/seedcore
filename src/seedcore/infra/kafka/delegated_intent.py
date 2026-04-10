from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from seedcore.api.external_authority import OwnerContextPreflightRequest
from seedcore.infra.kafka.envelope import build_stream_envelope
from seedcore.models.agent_action_gateway import AgentActionEvaluateRequest

DELEGATED_INTENT_PAYLOAD_SCHEMA_VERSION = "seedcore.intent.delegated.v0"


class DelegatedIntentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stream: Literal["intent"] = "intent"
    payload_schema_version: Literal["seedcore.intent.delegated.v0"] = (
        DELEGATED_INTENT_PAYLOAD_SCHEMA_VERSION
    )
    request_id: str
    workflow_id: str | None = None
    correlation_id: str | None = None
    assistant_namespace: str | None = None
    owner_context_preflight: OwnerContextPreflightRequest
    gateway_request: AgentActionEvaluateRequest
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_request_alignment(self) -> "DelegatedIntentPayload":
        if self.request_id != self.gateway_request.request_id:
            raise ValueError("payload.request_id must equal gateway_request.request_id")
        if self.owner_context_preflight.owner_id != self.gateway_request.principal.owner_id:
            raise ValueError(
                "owner_context_preflight.owner_id must equal gateway_request.principal.owner_id"
            )

        gateway_assistant_id = str(self.gateway_request.principal.agent_id or "").strip() or None
        if (
            self.owner_context_preflight.assistant_id is not None
            and gateway_assistant_id is not None
            and self.owner_context_preflight.assistant_id != gateway_assistant_id
        ):
            raise ValueError(
                "owner_context_preflight.assistant_id must equal gateway_request.principal.agent_id"
            )
        return self


def build_delegated_intent_envelope(
    payload: DelegatedIntentPayload,
    *,
    producer: str,
) -> dict[str, Any]:
    return build_stream_envelope(payload.model_dump(mode="json"), producer=producer)

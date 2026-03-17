from typing import Any, Dict, Optional, List
import uuid

from .base import ToolBase
from .manager import ToolError
from seedcore.agents.bridges.hal_client import HALClient

class ForensicSealTool(ToolBase):
    """
    Tool for triggering a cryptographically sealed Honey Digital Twin event
    after physical actuation or custody transition.
    
    Maps to: HAL /forensic-seal endpoint
    """
    
    name = "forensic.seal"
    description = "Requests the HAL bridge to generate a cryptographically sealed Honey Digital Twin custody event for high-stakes audits."
    
    def __init__(self, hal_base_url: Optional[str] = None):
        super().__init__()
        self._hal_client = HALClient(base_url=hal_base_url)

    @property
    def schemas(self) -> List[Dict[str, Any]]:
        return [{
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {
                        "type": "string",
                        "description": "Unique URN for the custody event (e.g. urn:seedcore:event:honey-094-123)."
                    },
                    "platform_state": {
                        "type": "string",
                        "description": "State of the workflow (e.g., 'buyer-review-prepared')."
                    },
                    "trajectory_hash": {
                        "type": "string",
                        "description": "Hash of the intended or executed trajectory."
                    },
                    "policy_hash": {
                        "type": "string",
                        "description": "Hash of the OPA policy that authorized this action."
                    },
                    "auth_token": {
                        "type": "string",
                        "description": "The ExecutionToken or QA permit (e.g. 'QA-HONEY-FORENSIC')."
                    },
                    "from_zone": {
                        "type": "string",
                        "description": "Origin zone of the asset."
                    },
                    "to_zone": {
                        "type": "string",
                        "description": "Destination zone of the asset."
                    }
                },
                "required": [
                    "event_id", "platform_state", "trajectory_hash",
                    "policy_hash", "auth_token", "from_zone", "to_zone"
                ]
            }
        }]

    async def execute(self, params: Dict[str, Any]) -> Any:
        try:
            # 1. Provide default URN if not specified to prevent validation errors
            event_id = params.get("event_id") or f"urn:seedcore:event:honey-094-{str(uuid.uuid4())[:8]}"
            
            # 2. Call the HAL Client
            custody_event = await self._hal_client.request_forensic_seal(
                event_id=event_id,
                platform_state=params.get("platform_state", "buyer-review-prepared"),
                trajectory_hash=params.get("trajectory_hash", "sha256:unknown"),
                policy_hash=params.get("policy_hash", "sha256:unknown"),
                auth_token=params.get("auth_token", "QA-HONEY-FORENSIC"),
                from_zone=params.get("from_zone", "inspection-zone-a"),
                to_zone=params.get("to_zone", "sealed-buyer-review")
            )
            
            # 3. Clean up client
            await self._hal_client.close()
            
            # Return stringified JSON-LD for the Agent's reasoning history
            return {
                "status": "success",
                "message": "Honey Digital Twin custody event sealed successfully.",
                "custody_event": custody_event
            }
            
        except RuntimeError as e:
            return ToolError(str(e))
        except Exception as e:
            return ToolError(f"Unexpected error while sealing forensic event: {str(e)}")

async def register_forensic_tools(tool_manager: Any, hal_base_url: Optional[str] = None) -> bool:
    """
    Register Forensic tools with ToolManager.
    """
    import os
    try:
        base_url = (
            hal_base_url 
            or os.getenv("HAL_BASE_URL") 
            or "http://seedcore-hal-bridge:8003"
        )
        
        seal_tool = ForensicSealTool(hal_base_url=base_url)
        
        if hasattr(tool_manager, "register_internal"):
            await tool_manager.register_internal(seal_tool)
        elif hasattr(tool_manager, "register_forensic_tools"):
            result = await tool_manager.register_forensic_tools.remote(hal_base_url=base_url)
            return bool(result)
        elif hasattr(tool_manager, "register"):
            await tool_manager.register("forensic.seal", seal_tool)
        else:
            return False
        
        return True
    except Exception:
        return False

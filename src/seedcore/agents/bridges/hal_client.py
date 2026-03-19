import httpx
import logging
import os
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

class HALClient:
    """
    Client for the SeedCore Agent to securely interface with the HAL Bridge.
    Handles cryptographic seal requests and actuation intents for Zero-Trust custody.
    """

    def __init__(self, base_url: Optional[str] = None):
        # Default to K8s service name or localhost for dev
        self.base_url = base_url or os.getenv("HAL_BASE_URL", "http://seedcore-hal-bridge:8003")
        self.client = httpx.AsyncClient(timeout=10.0)

    async def request_forensic_seal(
        self,
        event_id: str,
        platform_state: str,
        trajectory_hash: Optional[str],
        policy_hash: str,
        auth_token: str,
        from_zone: str,
        to_zone: str,
        transition_receipt: Optional[Dict[str, Any]] = None,
        actuator_telemetry: Optional[Dict[str, Any]] = None,
        media_hash_references: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Requests the HAL bridge to generate a cryptographically sealed Honey Digital Twin custody event.
        
        Args:
            event_id: Unique URN for the custody event.
            platform_state: State of the workflow (e.g., 'buyer-review-prepared').
            trajectory_hash: Hash of the intended or executed trajectory.
            policy_hash: Hash of the OPA policy that authorized this action.
            auth_token: The ExecutionToken provided by the PDP.
            from_zone: Origin zone of the asset.
            to_zone: Destination zone of the asset.
            
        Returns:
            JSON-LD Dictionary representing the SeedCoreCustodyEvent.
        """
        endpoint = f"{self.base_url.rstrip('/')}/forensic-seal"
        
        payload = {
            "event_id": event_id,
            "platform_state": platform_state,
            "trajectory_hash": trajectory_hash,
            "policy_hash": policy_hash,
            "auth_token": auth_token,
            "from_zone": from_zone,
            "to_zone": to_zone,
            "transition_receipt": transition_receipt,
            "actuator_telemetry": actuator_telemetry or {},
            "media_hash_references": media_hash_references or [],
        }
        
        try:
            response = await self.client.post(endpoint, json=payload)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"HAL Forensic Seal failed with status {e.response.status_code}: {e.response.text}")
            raise RuntimeError(f"HAL Forensic Seal failed: {e.response.text}") from e
        except Exception as e:
            logger.error(f"HAL Request Error: {e}")
            raise RuntimeError(f"Failed to reach HAL Bridge: {e}") from e

    async def close(self):
        await self.client.aclose()

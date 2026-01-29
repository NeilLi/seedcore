"""
Tuya IoT Device Driver
======================

HAL driver implementation for Tuya IoT devices using the Tuya OpenAPI.

This driver provides low-level communication with Tuya devices, handling:
- HMAC-SHA256 authentication
- Token management and caching
- Device status queries
- Command sending

The driver is stateless and safe for concurrent use in Ray actors and
tool execution contexts.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any, Dict, Optional, List

import httpx  # pyright: ignore[reportMissingImports]

from ..interfaces import BaseIoTDeviceDriver
from seedcore.config.tuya_config import TuyaConfig
from seedcore.logging_setup import ensure_serve_logger, setup_logging

setup_logging(app_name="seedcore.hal.drivers.tuya")
logger = ensure_serve_logger("seedcore.hal.drivers.tuya", level="INFO")


class TuyaDriver(BaseIoTDeviceDriver):
    """
    Tuya OpenAPI driver for IoT device control.
    
    This driver implements the BaseIoTDeviceDriver interface, providing
    a HAL-compliant way to interact with Tuya devices. It handles all
    low-level API communication, authentication, and token management.
    
    The driver is:
    - Stateless (except cached token)
    - Thread-safe and Ray-actor-safe
    - Explicit about failures
    - Compatible with async/await patterns
    """

    def __init__(
        self,
        *,
        config: Optional[TuyaConfig] = None,
        access_id: Optional[str] = None,
        access_secret: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout_s: float = 10.0,
    ):
        """
        Initialize Tuya driver.
        
        Args:
            config: Optional TuyaConfig instance. If not provided, creates one.
            access_id: Optional override for access_id (takes precedence over config)
            access_secret: Optional override for access_secret (takes precedence over config)
            base_url: Optional override for base_url (takes precedence over config)
            timeout_s: HTTP timeout in seconds
        """
        super().__init__(config={})
        
        # Use provided config or create a new one
        self._config = config or TuyaConfig()
        
        # Check if Tuya is enabled
        if not self._config.enabled:
            raise RuntimeError(
                "Tuya is not enabled. Set TUYA_ENABLED=true and configure required env vars."
            )
        
        # Use provided overrides or fall back to config values
        self.access_id = access_id or self._config.access_id
        self.access_secret = access_secret or self._config.access_secret
        self.base_url = base_url or self._config.api_base or "https://openapi.tuya.com"

        if not self.access_id or not self.access_secret:
            raise RuntimeError("Tuya ACCESS_ID / ACCESS_SECRET not configured")

        self._http = httpx.AsyncClient(timeout=timeout_s)

        # Token cache
        self._token: Optional[str] = None
        self._token_expire_at: float = 0.0

    # ---------------------------------------------------------------------
    # Low-level signing & auth
    # ---------------------------------------------------------------------

    def _now_ms(self) -> str:
        """Get current timestamp in milliseconds as string."""
        return str(int(time.time() * 1000))

    def _hmac_sha256(self, message: str) -> str:
        """Generate HMAC-SHA256 signature."""
        return hmac.new(
            self.access_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest().upper()

    async def _sign(
        self,
        *,
        method: str,
        path: str,
        body: str = "",
        token: Optional[str] = None,
    ) -> Dict[str, str]:
        """
        Build Tuya OpenAPI HMAC-SHA256 signature headers.

        StringToSign:
            client_id + access_token(optional) + t + method + path + body
        """
        t = self._now_ms()

        sign_str = (
            f"{self.access_id}"
            f"{token or ''}"
            f"{t}"
            f"{method.upper()}"
            f"{path}"
            f"{body}"
        )

        sign = self._hmac_sha256(sign_str)

        headers = {
            "client_id": self.access_id,
            "t": t,
            "sign_method": "HMAC-SHA256",
            "sign": sign,
            "Content-Type": "application/json",
        }

        if token:
            headers["access_token"] = token

        return headers

    # ---------------------------------------------------------------------
    # Token management
    # ---------------------------------------------------------------------

    async def _ensure_token(self) -> str:
        """
        Fetch or reuse access token.
        
        Returns:
            Valid access token string
        """
        now = time.time()
        if self._token and now < self._token_expire_at:
            return self._token

        path = "/v1.0/token?grant_type=1"
        headers = await self._sign(method="GET", path=path)

        resp = await self._http.get(self.base_url + path, headers=headers)
        resp.raise_for_status()

        payload = resp.json()
        if not payload.get("success"):
            raise RuntimeError(f"Tuya token error: {payload}")

        result = payload["result"]
        self._token = result["access_token"]
        self._token_expire_at = now + int(result["expire_time"]) - 30

        logger.debug("Tuya access token refreshed")
        return self._token

    # ---------------------------------------------------------------------
    # BaseIoTDeviceDriver implementation
    # ---------------------------------------------------------------------

    async def get_device_status(self, device_id: str) -> Dict[str, Any]:
        """
        Query current status of a Tuya device.
        
        Args:
            device_id: Tuya device ID
            
        Returns:
            Dictionary with device status. Format:
            {
                "device_id": str,
                "status": dict  # Tuya API response
            }
        """
        if not device_id:
            raise ValueError("device_id is required")
        
        token = await self._ensure_token()
        path = f"/v1.0/devices/{device_id}/status"
        headers = await self._sign(method="GET", path=path, token=token)

        resp = await self._http.get(self.base_url + path, headers=headers)
        resp.raise_for_status()
        
        result = resp.json()
        
        return {
            "device_id": device_id,
            "status": result,
        }

    async def send_commands(
        self,
        device_id: str,
        commands: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Send commands to a Tuya device.

        Args:
            device_id: Tuya device ID
            commands: List of command dictionaries. Each command must have:
                - "code": str - DP code (e.g., "switch_led")
                - "value": Any - Command value (e.g., True, 100, "red")
                
        Returns:
            Dictionary with command response. Format:
            {
                "device_id": str,
                "commands": List[dict],  # Echo of sent commands
                "tuya_response": dict  # Tuya API response
            }
            
        Example:
            >>> driver = TuyaDriver()
            >>> await driver.send_commands(
            ...     "device123",
            ...     [{"code": "switch_led", "value": True}]
            ... )
        """
        if not device_id:
            raise ValueError("device_id is required")
        
        if not commands or not isinstance(commands, list):
            raise ValueError("commands must be a non-empty list")
        
        for cmd in commands:
            if not isinstance(cmd, dict):
                raise ValueError("each command must be a dict")
            if "code" not in cmd or "value" not in cmd:
                raise ValueError("each command must include 'code' and 'value'")
        
        token = await self._ensure_token()
        path = f"/v1.0/devices/{device_id}/commands"
        payload = {"commands": commands}
        body = json.dumps(payload, separators=(",", ":"))

        headers = await self._sign(
            method="POST",
            path=path,
            body=body,
            token=token,
        )

        resp = await self._http.post(
            self.base_url + path,
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        
        result = resp.json()
        
        return {
            "device_id": device_id,
            "commands": commands,
            "tuya_response": result,
        }

    # ---------------------------------------------------------------------
    # Lifecycle helpers
    # ---------------------------------------------------------------------

    async def close(self) -> None:
        """Close HTTP client and clean up resources."""
        await self._http.aclose()

    async def __aenter__(self) -> "TuyaDriver":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        """Async context manager exit."""
        await self.close()

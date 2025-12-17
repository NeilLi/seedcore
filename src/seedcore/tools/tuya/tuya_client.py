#!/usr/bin/env python
# seedcore/tools/tuya/tuya_client.py

"""
Tuya OpenAPI Client for IoT device control.

This module provides a client for interacting with Tuya's OpenAPI to control
and query Tuya IoT devices. It implements HMAC-SHA256 signing as required
by the Tuya OpenAPI authentication protocol.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Dict, Any

import httpx  # pyright: ignore[reportMissingImports]

import logging

logger = logging.getLogger(__name__)


class TuyaClient:
    """
    Client for Tuya OpenAPI.
    
    Handles authentication, signing, and HTTP requests to Tuya's cloud API.
    """
    
    def __init__(self, access_id: str, access_secret: str, region: str = ""):
        """
        Initialize Tuya client.
        
        Args:
            access_id: Tuya access ID (client_id)
            access_secret: Tuya access secret (client_secret)
            region: Tuya region code (e.g., "us", "eu", "cn", or "" for global)
        """
        self.access_id = access_id
        self.access_secret = access_secret
        self.region = region
        self.base_url = f"https://openapi.tuya{region}.com" if region else "https://openapi.tuyaus.com"
        self.http = httpx.AsyncClient(timeout=10.0)

    async def _sign(self, method: str, path: str, body: str = "") -> dict:
        """
        Implements Tuya HMAC-SHA256 signing.
        
        Tuya OpenAPI requires HMAC-SHA256 signing with the following headers:
        - client_id: The access ID
        - t: Unix timestamp in milliseconds
        - sign_method: "HMAC-SHA256"
        - sign: HMAC-SHA256 signature
        
        The string to sign is: client_id + t + method + path + body
        
        Args:
            method: HTTP method (GET, POST, etc.)
            path: API path (e.g., "/v1.0/devices/{device_id}/status")
            body: Request body as string (empty for GET requests)
            
        Returns:
            Dictionary of headers to include in the request
        """
        # Get current timestamp in milliseconds
        timestamp = str(int(time.time() * 1000))
        
        # Build string to sign: client_id + t + method + path + body
        string_to_sign = f"{self.access_id}{timestamp}{method.upper()}{path}{body}"
        
        # Calculate HMAC-SHA256 signature
        sign = hmac.new(
            self.access_secret.encode('utf-8'),
            string_to_sign.encode('utf-8'),
            hashlib.sha256
        ).hexdigest().upper()
        
        # Build headers
        headers = {
            "client_id": self.access_id,
            "t": timestamp,
            "sign_method": "HMAC-SHA256",
            "sign": sign,
            "Content-Type": "application/json",
        }
        
        return headers
    
    async def send_command(
        self, device_id: str, commands: list[dict]
    ) -> dict:
        """
        Send commands to a Tuya device.
        
        Args:
            device_id: Tuya device ID
            commands: List of command dictionaries with "code" and "value" keys
                Example: [{"code": "switch_led", "value": True}]
                
        Returns:
            Response dictionary from Tuya API
            
        Raises:
            httpx.HTTPStatusError: If the API request fails
        """
        path = f"/v1.0/devices/{device_id}/commands"
        payload = {"commands": commands}
        body = json.dumps(payload)
        headers = await self._sign("POST", path, body=body)
        
        try:
            resp = await self.http.post(
                self.base_url + path,
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Tuya API error sending command to {device_id}: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error sending command to {device_id}: {e}")
            raise

    async def get_status(self, device_id: str) -> dict:
        """
        Get the current status of a Tuya device.
        
        Args:
            device_id: Tuya device ID
            
        Returns:
            Response dictionary containing device status
            
        Raises:
            httpx.HTTPStatusError: If the API request fails
        """
        path = f"/v1.0/devices/{device_id}/status"
        headers = await self._sign("GET", path)
        
        try:
            resp = await self.http.get(self.base_url + path, headers=headers)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Tuya API error getting status for {device_id}: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error getting status for {device_id}: {e}")
            raise
    
    async def close(self) -> None:
        """Close the HTTP client."""
        await self.http.aclose()
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()

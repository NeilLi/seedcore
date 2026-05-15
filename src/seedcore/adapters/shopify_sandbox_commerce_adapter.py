from __future__ import annotations

from typing import Any, Dict

import httpx


class CommerceAdapterTimeout(TimeoutError):
    """Typed commerce-adapter timeout used by degraded-edge drills."""

    reason_code = "commerce_adapter_timeout"

    def __init__(self, message: str = "commerce adapter timed out") -> None:
        super().__init__(message)
        self.reason_code = self.__class__.reason_code


def map_shopify_sandbox_transaction_to_gateway_commerce_fields(
    *,
    product_ref: str,
    order_ref: str | None = None,
    quote_ref: str,
    declared_value_usd: float | int,
    economic_hash: str,
) -> Dict[str, Any]:
    """
    Narrow Shopify-Sandbox-shaped mapping into SeedCore's gateway contract fields.

    Output is designed to be merged into:
    - `asset.product_ref`
    - `asset.quote_ref`
    - `asset.declared_value_usd`
    - `forensic_context.fingerprint_components.economic_hash`
    """
    if product_ref is None:
        raise ValueError("commerce.product_ref must be non-empty")
    if quote_ref is None:
        raise ValueError("commerce.quote_ref must be non-empty")
    if economic_hash is None:
        raise ValueError("commerce.economic_hash must be non-empty")

    product_ref = str(product_ref).strip()
    quote_ref = str(quote_ref).strip()
    economic_hash = str(economic_hash).strip()

    if not product_ref:
        raise ValueError("commerce.product_ref must be non-empty")
    if not quote_ref:
        raise ValueError("commerce.quote_ref must be non-empty")
    if not economic_hash:
        raise ValueError("commerce.economic_hash must be non-empty")
    if product_ref.lower() == "none" or quote_ref.lower() == "none" or economic_hash.lower() == "none":
        raise ValueError("commerce fields must not be the string 'None'")
    declared_value = float(declared_value_usd)
    if declared_value < 0:
        raise ValueError("commerce.declared_value_usd must be >= 0")

    return {
        "asset": {
            "product_ref": product_ref,
            "order_ref": str(order_ref).strip() if order_ref is not None and str(order_ref).strip() else None,
            "quote_ref": quote_ref,
            "declared_value_usd": declared_value,
        },
        "forensic_context": {
            "fingerprint_components": {
                "economic_hash": economic_hash,
            }
        },
    }


async def fetch_shopify_sandbox_transaction_to_gateway_commerce_fields(
    *,
    transaction_url: str,
    client: httpx.AsyncClient | None = None,
    timeout: float = 2.0,
) -> Dict[str, Any]:
    """
    Fetch a Shopify-Sandbox-shaped transaction over HTTP and map it through
    the existing pure commerce mapper.

    This keeps the gateway payload contract unchanged while giving outage
    drills a real HTTP boundary to exercise.
    """
    close_client = client is None
    http_client = client or httpx.AsyncClient(timeout=timeout)
    try:
        response = await http_client.get(transaction_url)
        response.raise_for_status()
        transaction = response.json()
    except httpx.TimeoutException as exc:
        raise CommerceAdapterTimeout() from exc
    finally:
        if close_client:
            await http_client.aclose()

    if not isinstance(transaction, dict):
        raise ValueError("commerce transaction response must be a JSON object")

    return map_shopify_sandbox_transaction_to_gateway_commerce_fields(
        product_ref=transaction.get("product_ref"),
        order_ref=transaction.get("order_ref"),
        quote_ref=transaction.get("quote_ref"),
        declared_value_usd=transaction.get("declared_value_usd"),
        economic_hash=transaction.get("economic_hash"),
    )

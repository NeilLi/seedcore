from __future__ import annotations

from typing import Any, Dict


def map_shopify_sandbox_transaction_to_gateway_commerce_fields(
    *,
    product_ref: str,
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
            "quote_ref": quote_ref,
            "declared_value_usd": declared_value,
        },
        "forensic_context": {
            "fingerprint_components": {
                "economic_hash": economic_hash,
            }
        },
    }


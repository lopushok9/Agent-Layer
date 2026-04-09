"""Mayan cross-chain quote, token, and status providers."""

from __future__ import annotations

from typing import Any

from agent_wallet.config import settings
from agent_wallet.exceptions import ProviderError
from agent_wallet.http_client import get_client

_CHAIN_ALIASES = {
    "eth": "ethereum",
    "mainnet": "ethereum",
    "eth-mainnet": "ethereum",
    "base-mainnet": "base",
}

_SUPPORTED_CHAINS = {
    "solana",
    "ethereum",
    "bsc",
    "polygon",
    "avalanche",
    "arbitrum",
    "optimism",
    "base",
    "aptos",
    "sui",
    "unichain",
    "linea",
    "hypercore",
    "sonic",
    "hyperevm",
    "fogo",
    "monad",
}


def normalize_chain_name(value: str, *, field_name: str) -> str:
    chain = str(value or "").strip().lower()
    chain = _CHAIN_ALIASES.get(chain, chain)
    if chain not in _SUPPORTED_CHAINS:
        raise ProviderError("mayan", f"{field_name} is not supported by Mayan: {value}")
    return chain


def _headers() -> dict[str, str]:
    referer = settings.mayan_api_referer.strip() or "https://docs.mayan.finance"
    return {
        "Accept": "application/json",
        "referer": referer,
    }


def _with_api_key(params: dict[str, Any] | None = None) -> dict[str, Any]:
    query = dict(params or {})
    api_key = settings.mayan_api_key.strip()
    if api_key:
        query["apiKey"] = api_key
    return query


def _normalize_quote_error(payload: Any) -> str:
    if isinstance(payload, dict):
        message = payload.get("msg") or payload.get("message") or payload.get("error")
        if message:
            return str(message)
    return "Route not found."


async def fetch_supported_chains() -> list[dict[str, Any]]:
    client = get_client()
    response = await client.get(
        f"{settings.mayan_price_api_base_url.rstrip('/')}/chains",
        params=_with_api_key(),
        headers=_headers(),
    )
    payload = response.json()
    if response.status_code != 200:
        raise ProviderError("mayan", f"HTTP {response.status_code}: {_normalize_quote_error(payload)}")
    if not isinstance(payload, list):
        raise ProviderError("mayan", "Unexpected chains response from Mayan.")
    return [item for item in payload if isinstance(item, dict)]


async def fetch_tokens(
    *,
    chain: str,
    standard: str | None = None,
) -> list[dict[str, Any]]:
    normalized_chain = normalize_chain_name(chain, field_name="chain")
    params: dict[str, Any] = {"chain": normalized_chain}
    if isinstance(standard, str) and standard.strip():
        params["standard"] = standard.strip().lower()
    client = get_client()
    response = await client.get(
        f"{settings.mayan_price_api_base_url.rstrip('/')}/tokens",
        params=_with_api_key(params),
        headers=_headers(),
    )
    payload = response.json()
    if response.status_code != 200:
        raise ProviderError("mayan", f"HTTP {response.status_code}: {_normalize_quote_error(payload)}")
    if not isinstance(payload, dict) or not isinstance(payload.get(normalized_chain), list):
        raise ProviderError("mayan", "Unexpected token list response from Mayan.")
    return [item for item in payload[normalized_chain] if isinstance(item, dict)]


async def fetch_quote(
    *,
    from_chain: str,
    to_chain: str,
    from_token: str,
    to_token: str,
    amount_in_raw: str,
    slippage_bps: int | str = "auto",
    gas_drop: int | float | None = None,
    referrer: str | None = None,
    referrer_bps: int | None = None,
    destination_address: str | None = None,
    only_direct: bool = False,
    full_list: bool = False,
) -> dict[str, Any]:
    normalized_from_chain = normalize_chain_name(from_chain, field_name="from_chain")
    normalized_to_chain = normalize_chain_name(to_chain, field_name="to_chain")
    params: dict[str, Any] = {
        "wormhole": "true",
        "swift": "true",
        "mctp": "true",
        "fastMctp": "true",
        "monoChain": "true",
        "shuttle": "false",
        "gasless": "false",
        "onlyDirect": str(bool(only_direct)).lower(),
        "fullList": str(bool(full_list)).lower(),
        "solanaProgram": settings.mayan_solana_program_id.strip(),
        "forwarderAddress": settings.mayan_forwarder_contract.strip(),
        "amountIn64": amount_in_raw,
        "fromToken": from_token.strip(),
        "fromChain": normalized_from_chain,
        "toToken": to_token.strip(),
        "toChain": normalized_to_chain,
        "slippageBps": slippage_bps,
        "sdkVersion": settings.mayan_sdk_version.strip() or "13_3_0",
    }
    if gas_drop is not None:
        params["gasDrop"] = gas_drop
    if isinstance(referrer, str) and referrer.strip():
        params["referrer"] = referrer.strip()
    if isinstance(referrer_bps, int) and referrer_bps >= 0:
        params["referrerBps"] = referrer_bps
    if isinstance(destination_address, str) and destination_address.strip():
        params["destinationAddress"] = destination_address.strip()

    client = get_client()
    response = await client.get(
        f"{settings.mayan_price_api_base_url.rstrip('/')}/quote",
        params=_with_api_key(params),
        headers=_headers(),
    )
    payload = response.json()
    if response.status_code not in {200, 201}:
        raise ProviderError("mayan", f"HTTP {response.status_code}: {_normalize_quote_error(payload)}")
    if not isinstance(payload, dict) or not isinstance(payload.get("quotes"), list):
        raise ProviderError("mayan", "Unexpected quote response from Mayan.")
    return payload


async def fetch_swap_status_by_tx_hash(source_tx_hash: str) -> dict[str, Any]:
    client = get_client()
    response = await client.get(
        f"{settings.mayan_explorer_api_base_url.rstrip('/')}/swap/trx/{source_tx_hash.strip()}",
        params=_with_api_key(),
        headers=_headers(),
    )
    payload = response.json()
    if response.status_code != 200:
        raise ProviderError("mayan", f"HTTP {response.status_code}: {_normalize_quote_error(payload)}")
    if not isinstance(payload, dict):
        raise ProviderError("mayan", "Unexpected swap status response from Mayan.")
    return payload

"""LI.FI cross-chain quote and status provider."""

from __future__ import annotations

from typing import Any

from agent_wallet.config import settings
from agent_wallet.exceptions import ProviderError
from agent_wallet.http_client import get_client

EVM_NATIVE_TOKEN = "0x0000000000000000000000000000000000000000"
SOLANA_NATIVE_TOKEN = "11111111111111111111111111111111"

_CHAIN_ALIASES = {
    "1": "1",
    "eth": "1",
    "ethereum": "1",
    "mainnet": "1",
    "eth-mainnet": "1",
    "8453": "8453",
    "base": "8453",
    "base-mainnet": "8453",
    "1151111081099710": "1151111081099710",
    "sol": "1151111081099710",
    "solana": "1151111081099710",
}

_CHAIN_NAMES_BY_ID = {
    "1": "ethereum",
    "8453": "base",
    "1151111081099710": "solana",
}

OPENCLAW_SUPPORTED_CHAINS = [
    {"chain": "ethereum", "chain_id": "1", "key": "eth", "name": "Ethereum", "coin": "ETH"},
    {"chain": "base", "chain_id": "8453", "key": "bas", "name": "Base", "coin": "ETH"},
    {"chain": "solana", "chain_id": "1151111081099710", "key": "sol", "name": "Solana", "coin": "SOL"},
]
_KNOWN_EVM_TOKEN_ADDRESSES = {
    "1": {
        "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "0xdac17f958d2ee523a2206206994597c13d831ec7": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
    },
    "8453": {
        "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    },
}


def normalize_chain_id(value: str, *, field_name: str) -> str:
    chain = str(value or "").strip().lower()
    normalized = _CHAIN_ALIASES.get(chain, chain)
    if normalized not in _CHAIN_NAMES_BY_ID:
        raise ProviderError("lifi", f"{field_name} is not supported by OpenClaw LI.FI routing: {value}")
    return normalized


def chain_name_for_id(chain_id: str) -> str:
    return _CHAIN_NAMES_BY_ID.get(str(chain_id), str(chain_id))


def normalize_token_address(token: str, *, chain_id: str) -> str:
    text = str(token or "").strip()
    if not text:
        raise ProviderError("lifi", "token address is required.")
    alias = text.lower()
    if chain_id == "1151111081099710" and alias in {"native", "sol", "solana"}:
        return SOLANA_NATIVE_TOKEN
    if chain_id in {"1", "8453"} and alias in {"native", "eth", "ethereum"}:
        return EVM_NATIVE_TOKEN
    if chain_id in _KNOWN_EVM_TOKEN_ADDRESSES:
        return _KNOWN_EVM_TOKEN_ADDRESSES[chain_id].get(alias, text)
    return text


def format_openclaw_supported_chains(chains: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return OpenClaw's supported LI.FI subset, including Solana if omitted from discovery."""
    items = [
        {
            "chain_id": str(item.get("id") or item.get("chainId") or "").strip(),
            "key": str(item.get("key") or "").strip() or None,
            "name": str(item.get("name") or "").strip() or None,
            "coin": str(item.get("coin") or "").strip() or None,
            "native_token": item.get("nativeToken"),
            "raw": item,
        }
        for item in chains
    ]
    supported_ids = {chain["chain_id"] for chain in OPENCLAW_SUPPORTED_CHAINS}
    supported_keys = {chain["key"] for chain in OPENCLAW_SUPPORTED_CHAINS}
    supported_by_id = {
        item["chain_id"]: item
        for item in items
        if item["chain_id"] in supported_ids or str(item.get("key") or "").lower() in supported_keys
    }
    for chain in OPENCLAW_SUPPORTED_CHAINS:
        supported_by_id.setdefault(
            chain["chain_id"],
            {
                "chain_id": chain["chain_id"],
                "key": chain["key"],
                "name": chain["name"],
                "coin": chain["coin"],
                "native_token": None,
                "raw": None,
            },
        )
    return [supported_by_id[chain["chain_id"]] for chain in OPENCLAW_SUPPORTED_CHAINS]


def _headers() -> dict[str, str]:
    headers = {
        "Accept": "application/json",
    }
    api_key = settings.lifi_api_key.strip()
    if api_key:
        headers["x-lifi-api-key"] = api_key
    return headers


def _base_url() -> str:
    return settings.lifi_api_base_url.rstrip("/")


def _normalize_error(payload: Any) -> str:
    if isinstance(payload, dict):
        message = (
            payload.get("message")
            or payload.get("error")
            or payload.get("detail")
            or payload.get("description")
        )
        if message:
            return str(message)
        errors = payload.get("errors")
        if isinstance(errors, list) and errors:
            return "; ".join(str(item) for item in errors[:3])
    return "Route not found."


def _csv(value: str | list[str] | tuple[str, ...] | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, (list, tuple)):
        items = [str(item).strip() for item in value if str(item).strip()]
        return ",".join(items) if items else None
    return str(value).strip() or None


def _clean_params(params: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        cleaned[key] = value
    return cleaned


async def fetch_supported_chains() -> list[dict[str, Any]]:
    client = get_client()
    response = await client.get(
        f"{_base_url()}/chains",
        headers=_headers(),
    )
    payload = response.json()
    if response.status_code != 200:
        raise ProviderError("lifi", f"HTTP {response.status_code}: {_normalize_error(payload)}")
    if isinstance(payload, dict) and isinstance(payload.get("chains"), list):
        return [item for item in payload["chains"] if isinstance(item, dict)]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    raise ProviderError("lifi", "Unexpected chains response from LI.FI.")


async def fetch_quote(
    *,
    from_chain: str,
    to_chain: str,
    from_token: str,
    to_token: str,
    amount_in_raw: str,
    from_address: str,
    to_address: str,
    slippage: float | int | None = None,
    integrator: str | None = None,
    allow_bridges: str | list[str] | None = None,
    deny_bridges: str | list[str] | None = None,
    prefer_bridges: str | list[str] | None = None,
) -> dict[str, Any]:
    from_chain_id = normalize_chain_id(from_chain, field_name="from_chain")
    to_chain_id = normalize_chain_id(to_chain, field_name="to_chain")
    default_deny_bridges = settings.lifi_default_deny_bridges.strip()
    params = _clean_params(
        {
            "fromChain": from_chain_id,
            "toChain": to_chain_id,
            "fromToken": normalize_token_address(from_token, chain_id=from_chain_id),
            "toToken": normalize_token_address(to_token, chain_id=to_chain_id),
            "fromAmount": str(amount_in_raw).strip(),
            "fromAddress": str(from_address).strip(),
            "toAddress": str(to_address).strip(),
            "slippage": slippage,
            "integrator": (integrator or settings.lifi_integrator).strip(),
            "allowBridges": _csv(allow_bridges),
            "denyBridges": _csv(deny_bridges) if deny_bridges is not None else _csv(default_deny_bridges),
            "preferBridges": _csv(prefer_bridges),
        }
    )
    client = get_client()
    response = await client.get(
        f"{_base_url()}/quote",
        params=params,
        headers=_headers(),
    )
    payload = response.json()
    if response.status_code != 200:
        raise ProviderError("lifi", f"HTTP {response.status_code}: {_normalize_error(payload)}")
    if not isinstance(payload, dict):
        raise ProviderError("lifi", "Unexpected quote response from LI.FI.")
    return payload


async def fetch_transfer_status(
    *,
    tx_hash: str,
    bridge: str | None = None,
    from_chain: str | None = None,
    to_chain: str | None = None,
) -> dict[str, Any]:
    params = _clean_params(
        {
            "txHash": str(tx_hash).strip(),
            "bridge": str(bridge).strip() if isinstance(bridge, str) else None,
            "fromChain": normalize_chain_id(from_chain, field_name="from_chain") if from_chain else None,
            "toChain": normalize_chain_id(to_chain, field_name="to_chain") if to_chain else None,
        }
    )
    client = get_client()
    response = await client.get(
        f"{_base_url()}/status",
        params=params,
        headers=_headers(),
    )
    payload = response.json()
    if response.status_code != 200:
        raise ProviderError("lifi", f"HTTP {response.status_code}: {_normalize_error(payload)}")
    if not isinstance(payload, dict):
        raise ProviderError("lifi", "Unexpected status response from LI.FI.")
    return payload

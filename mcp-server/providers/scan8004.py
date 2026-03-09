"""8004scan provider — off-chain ERC-8004 agent discovery across chains."""

import logging
from urllib.parse import urlencode

from config import settings
from exceptions import ProviderError
from http_client import get_client
from rate_limiter import RateLimiter

log = logging.getLogger(__name__)

_limiter = RateLimiter(max_calls=settings.rate_limit_scan8004, window_seconds=60)


def _normalize_chain_value(chain: str) -> str:
    return chain.strip().lower().replace("_", " ").replace("-", " ")


async def list_chains() -> list[dict]:
    """Return enabled chains from 8004scan."""
    await _limiter.acquire()
    url = f"{settings.scan8004_api_url.rstrip('/')}/api/v1/chains"
    client = get_client()

    try:
        resp = await client.get(url)
    except Exception as exc:
        raise ProviderError("8004scan", f"HTTP error: {exc}") from exc

    if resp.status_code != 200:
        raise ProviderError("8004scan", f"HTTP {resp.status_code}: {resp.text[:200]}")

    payload = resp.json()
    data = payload.get("data", {})
    chains = data.get("chains", [])
    if not isinstance(chains, list):
        return []
    return [c for c in chains if isinstance(c, dict) and c.get("enabled", True)]


async def resolve_chain_id(chain: str) -> int | None:
    """Resolve chain name/slug to chain_id, e.g. 'base' -> 8453."""
    if not chain.strip():
        return None

    norm = _normalize_chain_value(chain)
    chains = await list_chains()
    aliases = {
        "eth": "ethereum mainnet",
        "ethereum": "ethereum mainnet",
        "arb": "arbitrum one",
        "arbitrum": "arbitrum one",
    }
    target = aliases.get(norm, norm)

    for item in chains:
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        name_norm = _normalize_chain_value(name)
        if target == name_norm:
            return int(item["chain_id"])
        if target in name_norm:
            return int(item["chain_id"])
    return None


def _build_item(row: dict) -> dict:
    protocols_raw = row.get("supported_protocols") or []
    protocols = [str(p).upper() for p in protocols_raw if isinstance(p, str)]
    protocol_set = set(protocols)
    return {
        "agent_id": str(row.get("agent_id", "")),
        "chain_id": int(row.get("chain_id", 0)),
        "chain_name": None,
        "token_id": str(row.get("token_id", "")),
        "name": row.get("name"),
        "description": row.get("description"),
        "owner_address": str(row.get("owner_address", "")),
        "supported_protocols": protocols,
        "has_mcp": "MCP" in protocol_set,
        "has_a2a": "A2A" in protocol_set,
        "has_oasf": "OASF" in protocol_set,
        "x402_supported": bool(row.get("x402_supported", False)),
        "total_score": row.get("total_score"),
        "star_count": int(row.get("star_count", 0)),
        "is_testnet": row.get("is_testnet"),
        "source": "8004scan",
    }


def _normalize_service(protocol: str, payload: object) -> dict:
    if isinstance(payload, str):
        return {
            "protocol": protocol.upper(),
            "endpoint": payload,
            "version": None,
            "tools_count": 0,
            "prompt_count": 0,
            "resource_count": 0,
            "skill_count": 0,
            "tools": [],
            "skills": [],
        }

    if not isinstance(payload, dict):
        return {
            "protocol": protocol.upper(),
            "endpoint": None,
            "version": None,
            "tools_count": 0,
            "prompt_count": 0,
            "resource_count": 0,
            "skill_count": 0,
            "tools": [],
            "skills": [],
        }

    raw_tools = payload.get("tools") or []
    tool_names: list[str] = []
    if isinstance(raw_tools, list):
        for item in raw_tools:
            if isinstance(item, str):
                tool_names.append(item)
            elif isinstance(item, dict) and isinstance(item.get("name"), str):
                tool_names.append(item["name"])

    raw_skills = payload.get("skills") or []
    skills = [str(item) for item in raw_skills if isinstance(item, str)]
    prompts = payload.get("prompts") or []
    resources = payload.get("resources") or []

    return {
        "protocol": protocol.upper(),
        "endpoint": payload.get("endpoint"),
        "version": payload.get("version"),
        "tools_count": len(tool_names),
        "prompt_count": len(prompts) if isinstance(prompts, list) else 0,
        "resource_count": len(resources) if isinstance(resources, list) else 0,
        "skill_count": len(skills),
        "tools": tool_names[:50],
        "skills": skills[:50],
    }


def _build_profile(row: dict) -> dict:
    services_raw = row.get("services") or {}
    services: list[dict] = []
    if isinstance(services_raw, dict):
        for protocol, payload in services_raw.items():
            services.append(_normalize_service(str(protocol), payload))

    total_tools = sum(item["tools_count"] for item in services)
    total_skills = sum(item["skill_count"] for item in services)
    scores = row.get("scores") or {}
    rank = None
    if isinstance(scores, dict):
        raw_rank = scores.get("rank")
        if isinstance(raw_rank, int):
            rank = raw_rank

    return {
        "agent_id": str(row.get("agent_id", "")),
        "chain_id": int(row.get("chain_id", 0)),
        "token_id": str(row.get("token_id", "")),
        "contract_address": str(row.get("contract_address", "")),
        "chain_type": str(row.get("chain_type", "evm")),
        "is_testnet": row.get("is_testnet"),
        "name": row.get("name"),
        "description": row.get("description"),
        "owner_address": str(row.get("owner_address", "")),
        "creator_address": row.get("creator_address"),
        "agent_wallet": row.get("agent_wallet"),
        "image_url": row.get("image_url"),
        "supported_protocols": [str(p).upper() for p in (row.get("supported_protocols") or []) if isinstance(p, str)],
        "x402_supported": bool(row.get("x402_supported", False)),
        "services": services,
        "tags": [str(tag) for tag in (row.get("tags") or []) if isinstance(tag, str)],
        "categories": [str(cat) for cat in (row.get("categories") or []) if isinstance(cat, str)],
        "total_score": row.get("total_score"),
        "rank": rank,
        "star_count": int(row.get("star_count", 0)),
        "watch_count": int(row.get("watch_count", 0)),
        "available_tools_count": total_tools,
        "available_skills_count": total_skills,
        "source": "8004scan",
    }


async def search_agents(
    query: str,
    *,
    limit: int = 10,
    offset: int = 0,
    chain_id: int | None = None,
    semantic: bool = False,
    include_testnets: bool = False,
) -> dict:
    """Search agents via 8004scan off-chain index.

    Returns:
        {"total": int, "limit": int, "offset": int, "items": list[dict], "query_url": str}
    """
    await _limiter.acquire()
    if limit < 1 or limit > 50:
        raise ValueError("limit must be between 1 and 50")
    if offset < 0:
        raise ValueError("offset must be >= 0")

    params: dict[str, object] = {
        "limit": limit,
        "offset": offset,
    }
    if query.strip():
        params["search"] = query.strip()
    if chain_id is not None:
        params["chain_id"] = chain_id
    if not include_testnets:
        params["is_testnet"] = "false"

    endpoint = "/api/v1/agents"
    if semantic and query.strip():
        endpoint = "/api/v1/agents/search/semantic"
        params.pop("search", None)
        params["q"] = query.strip()

    base_url = settings.scan8004_api_url.rstrip("/")
    url = f"{base_url}{endpoint}"
    client = get_client()

    try:
        resp = await client.get(url, params=params)
    except Exception as exc:
        raise ProviderError("8004scan", f"HTTP error: {exc}") from exc

    if resp.status_code != 200:
        raise ProviderError("8004scan", f"HTTP {resp.status_code}: {resp.text[:300]}")

    payload = resp.json()
    rows = payload.get("items", [])
    if not isinstance(rows, list):
        rows = []

    items = [_build_item(row) for row in rows if isinstance(row, dict)]
    query_string = urlencode(params, doseq=True)
    return {
        "total": int(payload.get("total", len(items))),
        "limit": int(payload.get("limit", limit)),
        "offset": int(payload.get("offset", offset)),
        "items": items,
        "query_url": f"{url}?{query_string}" if query_string else url,
    }


async def get_agent_details(chain_id: int, token_id: str) -> dict:
    """Get structured agent details by chain_id and token_id."""
    await _limiter.acquire()
    if not token_id.strip():
        raise ValueError("token_id is required")

    base_url = settings.scan8004_api_url.rstrip("/")
    url = f"{base_url}/api/v1/agents/{chain_id}/{token_id.strip()}"
    client = get_client()

    try:
        resp = await client.get(url)
    except Exception as exc:
        raise ProviderError("8004scan", f"HTTP error: {exc}") from exc

    if resp.status_code == 404:
        raise ProviderError("8004scan", f"Agent not found for chain_id={chain_id}, token_id={token_id}")
    if resp.status_code != 200:
        raise ProviderError("8004scan", f"HTTP {resp.status_code}: {resp.text[:300]}")

    payload = resp.json()
    if not isinstance(payload, dict):
        raise ProviderError("8004scan", "Unexpected response shape from detail endpoint")
    return _build_profile(payload)

"""ERC-8004 AI Agent identity lookup tools."""

import json
import logging

from cache import Cache
from config import settings
from models import AgentIdentity, AgentSearchItem
from providers import erc8004, scan8004

log = logging.getLogger(__name__)


def register(mcp, cache: Cache):
    """Register ERC-8004 agent tools on the FastMCP server."""

    @mcp.tool()
    async def get_agent_by_id(agent_id: int) -> str:
        """Look up an AI agent registered in the ERC-8004 IdentityRegistry on Ethereum.

        Reads on-chain identity data for a given agent ID: existence, owner address,
        agent wallet, and metadata URI (tokenURI).

        Requires ALCHEMY_API_KEY.

        Args:
            agent_id: The agent's token ID (uint256) in the IdentityRegistry contract.

        Returns:
            JSON object with agent_id, exists, owner, agent_wallet, agent_uri.

        Examples:
            Existing agent:
                Input: {"agent_id": 1}
                Output: {"agent_id": 1, "exists": true, "owner": "0x9ce7...", "agent_wallet": "0x9ce7...", "agent_uri": null}

            Non-existent agent:
                Input: {"agent_id": 99999999}
                Output: {"agent_id": 99999999, "exists": false, "owner": null, "agent_wallet": null, "agent_uri": null}
        """
        if agent_id < 0:
            raise ValueError(
                f"Invalid agent_id: {agent_id}. Must be a non-negative integer (uint256)."
            )

        cache_key = f"agent_identity:{agent_id}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            raw = await erc8004.fetch_agent_identity(agent_id)
            data = AgentIdentity(**raw).model_dump()
            result = json.dumps(data, ensure_ascii=False)

            # Cache for shorter time if agent doesn't exist (might be minted soon)
            ttl = settings.cache_ttl_agent_identity if data["exists"] else 15
            cache.set(cache_key, result, ttl)
            return result
        except Exception:
            stale = cache.get_stale(cache_key, settings.cache_stale_max_age)
            if stale is not None:
                return stale
            raise

    @mcp.tool()
    async def list_erc8004_chains() -> str:
        """List chains indexed by the off-chain 8004 explorer.

        Useful to discover chain IDs before calling `search_erc8004_agents`.
        Especially relevant for Base (`8453`) and Base Sepolia (`84532`).
        """
        cache_key = "agent_search:chains"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            chains = await scan8004.list_chains()
            result = json.dumps(chains, ensure_ascii=False)
            cache.set(cache_key, result, settings.cache_ttl_agent_search)
            return result
        except Exception:
            stale = cache.get_stale(cache_key, settings.cache_stale_max_age)
            if stale is not None:
                return stale
            raise

    @mcp.tool()
    async def search_erc8004_agents(
        query: str = "",
        chain: str = "base",
        limit: int = 10,
        include_testnets: bool = False,
        semantic: bool = False,
    ) -> str:
        """Search ERC-8004 agents off-chain via 8004 explorer index.

        This is a fast directory search (not direct on-chain crawling).
        Supports Base and other chains by name.

        Args:
            query: Free-text query (name/description/protocol tags). Empty = list mode.
            chain: Chain name/slug. Examples: "base", "ethereum", "arbitrum", "" for all.
            limit: Number of results to return (1-50).
            include_testnets: Include testnet chains when true.
            semantic: Use semantic search endpoint when true (requires non-empty query).

        Returns:
            JSON object with total/limit/offset/items/query_url.
        """
        chain_normalized = chain.strip().lower()
        if limit < 1 or limit > 50:
            raise ValueError("limit must be between 1 and 50")

        chain_id = None
        if chain_normalized:
            chain_id = await scan8004.resolve_chain_id(chain_normalized)
            if chain_id is None:
                raise ValueError(
                    f"Unknown chain: {chain}. Use list_erc8004_chains() to discover valid names."
                )

        cache_key = (
            "agent_search:"
            f"q={query.strip().lower()}:"
            f"chain={chain_normalized or 'all'}:"
            f"chain_id={chain_id}:"
            f"limit={limit}:"
            f"testnets={int(include_testnets)}:"
            f"semantic={int(semantic)}"
        )
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            raw = await scan8004.search_agents(
                query=query,
                limit=limit,
                offset=0,
                chain_id=chain_id,
                semantic=semantic,
                include_testnets=include_testnets,
            )
            normalized_items = [AgentSearchItem(**item).model_dump() for item in raw.get("items", [])]
            payload = {
                "total": raw.get("total", len(normalized_items)),
                "limit": raw.get("limit", limit),
                "offset": raw.get("offset", 0),
                "chain": chain if chain else None,
                "chain_id": chain_id,
                "include_testnets": include_testnets,
                "semantic": semantic,
                "items": normalized_items,
                "query_url": raw.get("query_url"),
            }
            result = json.dumps(payload, ensure_ascii=False)
            cache.set(cache_key, result, settings.cache_ttl_agent_search)
            return result
        except Exception:
            stale = cache.get_stale(cache_key, settings.cache_stale_max_age)
            if stale is not None:
                return stale
            raise

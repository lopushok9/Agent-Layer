"""ERC-8004 AI Agent identity lookup tools."""

import json
import logging

from cache import Cache
from config import settings
from models import AgentIdentity
from providers import erc8004

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

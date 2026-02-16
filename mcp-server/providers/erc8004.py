"""ERC-8004 IdentityRegistry provider — AI agent identity lookup on Ethereum.

Reads agent identity data from the ERC-8004 IdentityRegistry contract
using batch JSON-RPC eth_call via Alchemy.

Contract: 0x8004A169FB4a3325136EB29fA0ceB6D2e539a432 (Ethereum mainnet)
"""

import logging

from config import settings
from exceptions import ProviderError
from http_client import get_client
from rate_limiter import RateLimiter

log = logging.getLogger(__name__)

_limiter = RateLimiter(max_calls=settings.rate_limit_alchemy, window_seconds=60)

IDENTITY_REGISTRY = "0x8004A169FB4a3325136EB29fA0ceB6D2e539a432"

# Pre-computed keccak256 function selectors (first 4 bytes)
_SEL_OWNER_OF = "6352211e"        # ownerOf(uint256)
_SEL_TOKEN_URI = "c87b56dd"       # tokenURI(uint256)
_SEL_GET_AGENT_WALLET = "00339509"  # getAgentWallet(uint256)

ZERO_ADDRESS = "0x" + "0" * 40


def _encode_uint256(value: int) -> str:
    """ABI-encode a uint256 as 64-char hex (no 0x prefix)."""
    return hex(value)[2:].zfill(64)


def _encode_call(selector: str, agent_id: int) -> str:
    """Build calldata: 0x + selector + abi-encoded uint256."""
    return "0x" + selector + _encode_uint256(agent_id)


def _decode_address(hex_data: str) -> str | None:
    """Decode ABI-encoded address from eth_call result."""
    raw = hex_data.replace("0x", "")
    if len(raw) < 64 or raw == "0" * 64:
        return None
    addr = "0x" + raw[-40:]
    if addr == ZERO_ADDRESS:
        return None
    return addr


def _decode_string(hex_data: str) -> str | None:
    """Decode ABI-encoded string from eth_call result.

    ABI layout: [32-byte offset][32-byte length][data...]
    """
    raw = hex_data.replace("0x", "")
    if len(raw) < 128:
        return None

    try:
        # offset (should be 0x20 = 32)
        str_len = int(raw[64:128], 16)
        if str_len == 0:
            return None
        data_hex = raw[128 : 128 + str_len * 2]
        return bytes.fromhex(data_hex).decode("utf-8", errors="replace")
    except (ValueError, IndexError):
        return None


def _get_alchemy_url() -> str:
    """Build Alchemy Ethereum mainnet URL."""
    if not settings.alchemy_api_key:
        raise ProviderError("erc8004", "ALCHEMY_API_KEY is required for ERC-8004 agent lookup")
    return f"https://eth-mainnet.g.alchemy.com/v2/{settings.alchemy_api_key}"


async def fetch_agent_identity(agent_id: int) -> dict:
    """Fetch agent identity from IdentityRegistry via batch eth_call.

    Sends 3 calls in a single HTTP request:
      1. ownerOf(agentId) — determines existence
      2. tokenURI(agentId) — metadata URI
      3. getAgentWallet(agentId) — agent's wallet address

    Returns dict with: agent_id, exists, owner, agent_wallet, agent_uri, source.
    """
    await _limiter.acquire()

    url = _get_alchemy_url()
    client = get_client()

    call_params = {"to": IDENTITY_REGISTRY}
    batch = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_call",
            "params": [{**call_params, "data": _encode_call(_SEL_OWNER_OF, agent_id)}, "latest"],
        },
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "eth_call",
            "params": [{**call_params, "data": _encode_call(_SEL_TOKEN_URI, agent_id)}, "latest"],
        },
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "eth_call",
            "params": [{**call_params, "data": _encode_call(_SEL_GET_AGENT_WALLET, agent_id)}, "latest"],
        },
    ]

    try:
        resp = await client.post(url, json=batch)
    except Exception as exc:
        raise ProviderError("erc8004", f"HTTP error: {exc}") from exc

    if resp.status_code != 200:
        raise ProviderError("erc8004", f"HTTP {resp.status_code}")

    results_raw = resp.json()

    # Index by JSON-RPC id
    by_id: dict[int, dict] = {}
    for item in results_raw:
        by_id[item["id"]] = item

    # 1) ownerOf — determines existence
    owner_resp = by_id.get(1, {})
    if "error" in owner_resp:
        # Revert = agent does not exist
        return {
            "agent_id": agent_id,
            "exists": False,
            "owner": None,
            "agent_wallet": None,
            "agent_uri": None,
            "source": "erc8004",
        }

    owner = _decode_address(owner_resp.get("result", "0x"))

    # 2) tokenURI
    uri_resp = by_id.get(2, {})
    agent_uri = None
    if "error" not in uri_resp:
        agent_uri = _decode_string(uri_resp.get("result", "0x"))

    # 3) getAgentWallet
    wallet_resp = by_id.get(3, {})
    agent_wallet = None
    if "error" not in wallet_resp:
        agent_wallet = _decode_address(wallet_resp.get("result", "0x"))

    return {
        "agent_id": agent_id,
        "exists": owner is not None,
        "owner": owner,
        "agent_wallet": agent_wallet,
        "agent_uri": agent_uri,
        "source": "erc8004",
    }

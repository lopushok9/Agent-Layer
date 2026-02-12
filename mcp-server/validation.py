"""Input validation helpers for MCP tools.

Raises ValueError with actionable messages that help AI agents
understand what went wrong and how to fix the input.
"""

import re

ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")

SUPPORTED_CHAINS_RPC = {"ethereum", "base", "arbitrum", "polygon", "optimism", "bsc"}
SUPPORTED_CHAINS_EXPLORER = {"ethereum", "arbitrum", "base"}
SUPPORTED_CHAINS_ALCHEMY = {"ethereum", "base", "arbitrum", "polygon", "optimism"}

SUPPORTED_CHAINS_DEFI = {
    "Ethereum", "Arbitrum", "Base", "Polygon", "Optimism", "BSC",
    "Avalanche", "Fantom", "Solana", "Sui",
}


def validate_address(address: str) -> str:
    """Validate EVM wallet address (0x + 40 hex chars)."""
    address = address.strip()
    if not address:
        raise ValueError(
            "Wallet address is required. "
            "Example: 0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"
        )
    if not address.startswith("0x"):
        raise ValueError(
            f"Invalid address: '{address}'. "
            "EVM addresses must start with '0x' followed by 40 hex characters. "
            "Example: 0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"
        )
    if not ADDRESS_RE.match(address):
        raise ValueError(
            f"Invalid address: '{address}' (length {len(address)}, expected 42). "
            "EVM addresses must be exactly 42 characters: '0x' + 40 hex digits [0-9a-fA-F]. "
            "Example: 0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"
        )
    return address


def validate_chain(chain: str, supported: set[str]) -> str:
    """Validate chain name against a set of supported chains."""
    chain_lower = chain.lower().strip()
    if chain_lower not in supported:
        raise ValueError(
            f"Unsupported chain: '{chain}'. "
            f"Supported chains: {', '.join(sorted(supported))}."
        )
    return chain_lower


def validate_symbols(symbols: list[str]) -> list[str]:
    """Validate and clean symbol list. Returns cleaned symbols."""
    if not symbols:
        raise ValueError(
            "At least one cryptocurrency symbol is required. "
            'Example: ["BTC", "ETH", "SOL"]'
        )
    cleaned = [s.strip() for s in symbols if s and s.strip()]
    if not cleaned:
        raise ValueError(
            "No valid symbols provided (all entries were empty). "
            'Example: ["BTC", "ETH", "SOL"]'
        )
    return cleaned[:50]

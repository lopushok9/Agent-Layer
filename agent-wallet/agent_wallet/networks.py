"""Canonical network identifiers used by agent-wallet policy gates.

The Python wallet backend owns approval and autonomous-execution policy. Keep
the selectable EVM network set and its mainnet identities here so additions
cannot silently reach one policy gate but miss another.
"""

EVM_CORE_MAINNETS = frozenset({"ethereum", "base", "robinhood", "goat"})
EVM_CORE_NETWORK_ALIASES = {
    "mainnet": "ethereum",
    "eth": "ethereum",
    "eth-mainnet": "ethereum",
    "base-mainnet": "base",
    "goat-mainnet": "goat",
}
EVM_CORE_TESTNETS = frozenset({"sepolia", "base-sepolia", "base_sepolia", "goat-testnet", "goat-testnet3"})
EVM_CORE_MAINNET_CAIP_IDS = frozenset({"eip155:1", "eip155:8453", "eip155:4663", "eip155:2345"})
GOAT_EVM_NETWORK_IDENTIFIERS = frozenset({"goat", "goat-mainnet", "eip155:2345"})

# The autonomous engine may also govern legacy supported operation classes
# outside the selectable EVM wallet surface. Keep that superset derived from
# the core EVM mainnet definition rather than re-listing its members.
AUTONOMOUS_MAINNET_NETWORKS = frozenset(
    {"mainnet", "mainnet-beta", "arbitrum", "optimism", "polygon"} | EVM_CORE_MAINNETS
)

"""Hermes Agent plugin bridge for AgentLayer wallet tools."""

from .schemas import AGENT_WALLET_INVOKE, AGENT_WALLET_TOOLS
from .tools import agent_wallet_invoke, agent_wallet_tools


def register(ctx):
    """Register a narrow dispatcher instead of duplicating wallet tools."""
    ctx.register_tool(
        name=AGENT_WALLET_TOOLS["name"],
        toolset="agent_wallet",
        schema=AGENT_WALLET_TOOLS,
        handler=agent_wallet_tools,
        description=AGENT_WALLET_TOOLS["description"],
    )
    ctx.register_tool(
        name=AGENT_WALLET_INVOKE["name"],
        toolset="agent_wallet",
        schema=AGENT_WALLET_INVOKE,
        handler=agent_wallet_invoke,
        description=AGENT_WALLET_INVOKE["description"],
    )

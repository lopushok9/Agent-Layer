"""Optional AgentLayer connector contracts and local registry support."""

from agent_wallet.connectors.catalog import enabled_connector_tools, resolve_connector_tool
from agent_wallet.connectors.client import ConnectorInvocationError, ConnectorReadClient
from agent_wallet.connectors.intent_policy import (
    ConnectorIntentPolicyError,
    validate_evm_transaction_intent,
)
from agent_wallet.connectors.manifest import (
    ConnectorManifestError,
    connector_tool_name,
    validate_connector_manifest,
)
from agent_wallet.connectors.registry import ConnectorRegistry, ConnectorRegistryError

__all__ = [
    "ConnectorManifestError",
    "ConnectorInvocationError",
    "ConnectorIntentPolicyError",
    "ConnectorReadClient",
    "ConnectorRegistry",
    "ConnectorRegistryError",
    "connector_tool_name",
    "enabled_connector_tools",
    "resolve_connector_tool",
    "validate_connector_manifest",
    "validate_evm_transaction_intent",
]

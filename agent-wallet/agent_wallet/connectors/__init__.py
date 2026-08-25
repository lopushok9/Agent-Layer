"""Optional AgentLayer connector contracts and local registry support."""

from agent_wallet.connectors.manifest import (
    ConnectorManifestError,
    connector_tool_name,
    validate_connector_manifest,
)

__all__ = [
    "ConnectorManifestError",
    "connector_tool_name",
    "validate_connector_manifest",
]


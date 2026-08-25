"""Build the safe host-facing catalog of enabled connector tools."""

from __future__ import annotations

from typing import Any

from agent_wallet.connectors.manifest import connector_tool_name
from agent_wallet.connectors.registry import ConnectorRegistry, ConnectorRegistryError


def enabled_connector_tools(
    registry: ConnectorRegistry | None = None,
    *,
    include_write: bool = False,
) -> list[dict[str, Any]]:
    """Return enabled tools, withholding writes until their policy is available."""

    active_registry = registry or ConnectorRegistry()
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in active_registry.list():
        if not entry["enabled"]:
            continue
        connector_id = str(entry["id"])
        version = str(entry["enabled_version"])
        manifest = active_registry.load_manifest(connector_id, version)
        for raw_tool in manifest["tools"]:
            if not isinstance(raw_tool, dict):
                raise ConnectorRegistryError(f"Connector tool is invalid: {connector_id}.")
            read_only = raw_tool.get("read_only") is True
            if not read_only and not include_write:
                continue
            host_name = connector_tool_name(connector_id, str(raw_tool.get("name") or ""))
            if host_name in seen:
                raise ConnectorRegistryError(f"Duplicate host connector tool name: {host_name}.")
            seen.add(host_name)
            result.append(
                {
                    "name": host_name,
                    "description": str(raw_tool["description"]),
                    "input_schema": raw_tool["input_schema"],
                    "output_schema": raw_tool["output_schema"],
                    "read_only": read_only,
                    "risk_level": str(raw_tool["risk_level"]),
                    "connector_id": connector_id,
                    "connector_version": version,
                    "connector_tool": str(raw_tool["name"]),
                    "connector_trust": str(manifest["trust"]),
                }
            )
    return sorted(result, key=lambda item: str(item["name"]))


def resolve_connector_tool(
    host_tool_name: str,
    registry: ConnectorRegistry | None = None,
    *,
    include_write: bool = False,
) -> dict[str, Any]:
    """Resolve one host tool through the enabled immutable catalog."""

    for tool in enabled_connector_tools(registry, include_write=include_write):
        if tool["name"] == host_tool_name:
            return tool
    raise ConnectorRegistryError(f"Enabled connector tool was not found: {host_tool_name}.")


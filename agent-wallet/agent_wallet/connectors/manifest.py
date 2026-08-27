"""Fail-closed validation for AgentLayer Connector manifests."""

from __future__ import annotations

import copy
import re
from typing import Any
from urllib.parse import urlparse


CONNECTOR_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)+$")
TOOL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
SEMVER_PATTERN = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")

TRUST_CLASSES = frozenset(
    {
        "community_read_only",
        "verified_read_only",
        "verified_write",
        "local_development",
    }
)
READ_ONLY_TRUST_CLASSES = frozenset({"community_read_only", "verified_read_only"})


class ConnectorManifestError(ValueError):
    """Raised when a connector manifest violates the public contract."""


def _require_dict(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConnectorManifestError(f"{field} must be an object.")
    return value


def _require_nonempty_string(value: Any, field: str, *, max_length: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConnectorManifestError(f"{field} must be a non-empty string.")
    normalized = value.strip()
    if len(normalized) > max_length:
        raise ConnectorManifestError(f"{field} exceeds the maximum length of {max_length}.")
    return normalized


def _require_https_url(value: Any, field: str) -> str:
    url = _require_nonempty_string(value, field, max_length=2048)
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ConnectorManifestError(f"{field} must be an HTTPS URL without embedded credentials.")
    if parsed.fragment:
        raise ConnectorManifestError(f"{field} must not contain a fragment.")
    return url


def _validate_tools(manifest: dict[str, Any]) -> None:
    tools = manifest.get("tools")
    if not isinstance(tools, list) or not tools:
        raise ConnectorManifestError("tools must be a non-empty array.")
    if len(tools) > 64:
        raise ConnectorManifestError("tools cannot contain more than 64 entries.")

    names: set[str] = set()
    read_only_trust = manifest["trust"] in READ_ONLY_TRUST_CLASSES
    for index, raw_tool in enumerate(tools):
        tool = _require_dict(raw_tool, f"tools[{index}]")
        name = _require_nonempty_string(tool.get("name"), f"tools[{index}].name", max_length=64)
        if not TOOL_NAME_PATTERN.fullmatch(name):
            raise ConnectorManifestError(f"tools[{index}].name has an invalid format.")
        if name in names:
            raise ConnectorManifestError(f"Duplicate connector tool name: {name}.")
        names.add(name)
        _require_nonempty_string(
            tool.get("description"), f"tools[{index}].description", max_length=500
        )
        if not isinstance(tool.get("read_only"), bool):
            raise ConnectorManifestError(f"tools[{index}].read_only must be boolean.")
        if read_only_trust and tool["read_only"] is not True:
            raise ConnectorManifestError(
                f"{manifest['trust']} connectors may expose only read-only tools."
            )
        if tool.get("risk_level") not in {"low", "medium", "high"}:
            raise ConnectorManifestError(
                f"tools[{index}].risk_level must be low, medium, or high."
            )
        _require_dict(tool.get("input_schema"), f"tools[{index}].input_schema")
        _require_dict(tool.get("output_schema"), f"tools[{index}].output_schema")


def _validate_permissions(manifest: dict[str, Any]) -> None:
    permissions = _require_dict(manifest.get("permissions"), "permissions")
    for field in ("wallet_address", "transaction_intents"):
        if not isinstance(permissions.get(field), bool):
            raise ConnectorManifestError(f"permissions.{field} must be boolean.")
    network_hosts = permissions.get("network_hosts")
    if not isinstance(network_hosts, list) or len(network_hosts) > 32:
        raise ConnectorManifestError("permissions.network_hosts must be an array of at most 32 hosts.")
    normalized_hosts: set[str] = set()
    for index, host in enumerate(network_hosts):
        normalized = _require_nonempty_string(
            host, f"permissions.network_hosts[{index}]", max_length=253
        ).lower()
        if "://" in normalized or "/" in normalized or "@" in normalized:
            raise ConnectorManifestError(
                f"permissions.network_hosts[{index}] must be a hostname, not a URL."
            )
        normalized_hosts.add(normalized)
    if len(normalized_hosts) != len(network_hosts):
        raise ConnectorManifestError("permissions.network_hosts must not contain duplicates.")

    trust = manifest["trust"]
    if trust in READ_ONLY_TRUST_CLASSES and permissions["transaction_intents"] is not False:
        raise ConnectorManifestError(f"{trust} connectors cannot request transaction intents.")
    if trust == "verified_write" and permissions["transaction_intents"] is not True:
        raise ConnectorManifestError(
            "verified_write connectors must explicitly request transaction_intents."
        )


def validate_connector_manifest(payload: Any) -> dict[str, Any]:
    """Validate and return a detached connector manifest.

    JSON Schema remains the public contract. This validator intentionally
    duplicates the security-sensitive invariants needed before registry writes,
    avoiding a runtime dependency on a general-purpose schema engine.
    """

    manifest = copy.deepcopy(_require_dict(payload, "manifest"))
    if manifest.get("schema_version") != 1:
        raise ConnectorManifestError("schema_version must be 1.")

    connector_id = _require_nonempty_string(manifest.get("id"), "id", max_length=128)
    if not CONNECTOR_ID_PATTERN.fullmatch(connector_id):
        raise ConnectorManifestError("id has an invalid format.")
    _require_nonempty_string(manifest.get("name"), "name", max_length=80)

    version = _require_nonempty_string(manifest.get("version"), "version", max_length=64)
    if not SEMVER_PATTERN.fullmatch(version):
        raise ConnectorManifestError("version must be valid semantic version text.")

    trust = manifest.get("trust")
    if trust not in TRUST_CLASSES:
        raise ConnectorManifestError(f"Unsupported connector trust class: {trust!r}.")

    publisher = _require_dict(manifest.get("publisher"), "publisher")
    _require_nonempty_string(publisher.get("id"), "publisher.id", max_length=64)
    _require_nonempty_string(publisher.get("name"), "publisher.name", max_length=80)

    agentlayer = _require_dict(manifest.get("agentlayer"), "agentlayer")
    if agentlayer.get("protocol_version") != 1:
        raise ConnectorManifestError("agentlayer.protocol_version must be 1.")
    _require_nonempty_string(
        agentlayer.get("runtime_range"), "agentlayer.runtime_range", max_length=100
    )

    transport = _require_dict(manifest.get("transport"), "transport")
    if transport.get("type") != "https":
        raise ConnectorManifestError("transport.type must be https.")
    _require_https_url(transport.get("url"), "transport.url")
    timeout_ms = transport.get("timeout_ms", 10000)
    if (
        not isinstance(timeout_ms, int)
        or isinstance(timeout_ms, bool)
        or not 100 <= timeout_ms <= 30000
    ):
        raise ConnectorManifestError("transport.timeout_ms must be an integer from 100 to 30000.")

    digest = manifest.get("artifact_digest")
    if digest is not None and (
        not isinstance(digest, str) or not DIGEST_PATTERN.fullmatch(digest)
    ):
        raise ConnectorManifestError("artifact_digest must be a lowercase sha256 digest.")
    if trust == "verified_write" and not digest:
        raise ConnectorManifestError("verified_write connectors require artifact_digest.")

    _validate_permissions(manifest)
    _validate_tools(manifest)
    return manifest


def connector_tool_name(connector_id: str, tool_name: str) -> str:
    """Return the stable host-facing tool namespace for a connector tool."""

    if not CONNECTOR_ID_PATTERN.fullmatch(connector_id):
        raise ConnectorManifestError("id has an invalid format.")
    if not TOOL_NAME_PATTERN.fullmatch(tool_name):
        raise ConnectorManifestError("tool name has an invalid format.")
    normalized_id = re.sub(r"[^a-z0-9]+", "_", connector_id).strip("_")
    return f"connector__{normalized_id}__{tool_name}"

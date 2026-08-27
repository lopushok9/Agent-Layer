"""HTTPS client for untrusted read-only connector endpoints."""

from __future__ import annotations

import ipaddress
import json
import socket
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Iterable
from urllib.parse import urlparse

import httpx
import httpcore
from jsonschema import Draft202012Validator, SchemaError, ValidationError

from agent_wallet.connectors.catalog import resolve_connector_tool
from agent_wallet.connectors.registry import ConnectorRegistry


MAX_CONNECTOR_RESPONSE_BYTES = 1024 * 1024
MAX_RESPONSE_LIFETIME_SECONDS = 300
Resolver = Callable[[str], Iterable[str]]


class ConnectorInvocationError(RuntimeError):
    """Raised when a connector request or response cannot be trusted."""


def _default_resolver(hostname: str) -> list[str]:
    try:
        records = socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ConnectorInvocationError(f"Connector hostname could not be resolved: {hostname}.") from exc
    return sorted({str(record[4][0]) for record in records})


def _validate_endpoint_url(url: str) -> str:
    parsed = urlparse(url)
    hostname = str(parsed.hostname or "").lower()
    if parsed.scheme != "https" or not hostname or parsed.username or parsed.password:
        raise ConnectorInvocationError("Connector endpoint must be public HTTPS without credentials.")
    if hostname == "localhost" or hostname.endswith(".localhost") or hostname.endswith(".local"):
        raise ConnectorInvocationError("Connector endpoint cannot use a local hostname.")
    return hostname


def _resolve_public_addresses(hostname: str, resolver: Resolver) -> list[str]:
    addresses = list(resolver(hostname))
    if not addresses:
        raise ConnectorInvocationError("Connector endpoint did not resolve to an address.")
    for raw_address in addresses:
        try:
            address = ipaddress.ip_address(raw_address)
        except ValueError as exc:
            raise ConnectorInvocationError("Connector endpoint resolved to an invalid address.") from exc
        if not address.is_global:
            raise ConnectorInvocationError(
                f"Connector endpoint resolved to a non-public address: {raw_address}."
            )
    return addresses


def _assert_public_endpoint(url: str, resolver: Resolver) -> None:
    """Validate mocked/injected clients that do not use the pinned transport."""

    _resolve_public_addresses(_validate_endpoint_url(url), resolver)


class _PinnedPublicNetworkBackend(httpcore.AsyncNetworkBackend):
    """Resolve and validate at connect time, then open TCP to the validated IP.

    HTTP Core retains the original origin hostname and therefore still uses it
    for TLS SNI and certificate verification. Only the TCP destination is
    replaced, closing the DNS-validation-to-connect race.
    """

    def __init__(
        self,
        resolver: Resolver,
        network_backend: httpcore.AsyncNetworkBackend | None = None,
    ) -> None:
        self._resolver = resolver
        self._network_backend = network_backend or httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[tuple[int, int, int | bytes]] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        addresses = _resolve_public_addresses(host.lower(), self._resolver)
        return await self._network_backend.connect_tcp(
            addresses[0],
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[tuple[int, int, int | bytes]] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        raise ConnectorInvocationError("Connector Unix socket transport is not allowed.")

    async def sleep(self, seconds: float) -> None:
        await self._network_backend.sleep(seconds)


class _PinnedPublicAsyncTransport(httpx.AsyncHTTPTransport):
    """HTTPX transport whose connection pool uses connect-time DNS pinning."""

    def __init__(self, resolver: Resolver) -> None:
        super().__init__(retries=0)
        self._pool = httpcore.AsyncConnectionPool(
            retries=0,
            network_backend=_PinnedPublicNetworkBackend(resolver),
        )


def _parse_expiry(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise ConnectorInvocationError("Connector response expires_at is required.")
    try:
        expiry = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ConnectorInvocationError("Connector response expires_at is invalid.") from exc
    if expiry.tzinfo is None:
        raise ConnectorInvocationError("Connector response expires_at must include a timezone.")
    now = datetime.now(timezone.utc)
    remaining = (expiry.astimezone(timezone.utc) - now).total_seconds()
    if remaining <= 0:
        raise ConnectorInvocationError("Connector response has expired.")
    if remaining > MAX_RESPONSE_LIFETIME_SECONDS:
        raise ConnectorInvocationError("Connector response expiry exceeds the allowed lifetime.")
    return expiry


def _validate_json(instance: Any, schema: dict[str, Any], *, label: str) -> None:
    try:
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(instance)
    except SchemaError as exc:
        raise ConnectorInvocationError(f"Connector {label} schema is invalid: {exc.message}") from exc
    except ValidationError as exc:
        raise ConnectorInvocationError(f"Connector {label} does not match its schema: {exc.message}") from exc


class ConnectorReadClient:
    """Invoke enabled read-only connector tools with strict identity binding."""

    def __init__(
        self,
        registry: ConnectorRegistry | None = None,
        *,
        http_client: httpx.AsyncClient | None = None,
        resolver: Resolver | None = None,
    ):
        self.registry = registry or ConnectorRegistry()
        self._http_client = http_client
        self._resolver = resolver or _default_resolver

    async def invoke(
        self,
        host_tool_name: str,
        arguments: dict[str, Any],
        *,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        tool = resolve_connector_tool(host_tool_name, self.registry, include_write=False)
        if tool["read_only"] is not True:
            raise ConnectorInvocationError("ConnectorReadClient accepts only read-only tools.")
        if not isinstance(arguments, dict):
            raise ConnectorInvocationError("Connector tool arguments must be an object.")
        _validate_json(arguments, tool["input_schema"], label="tool input")

        connector_id = str(tool["connector_id"])
        connector_version = str(tool["connector_version"])
        manifest = self.registry.load_manifest(connector_id, connector_version)
        transport = manifest["transport"]
        base_url = str(transport["url"]).rstrip("/")
        _validate_endpoint_url(base_url)
        if self._http_client is not None:
            _assert_public_endpoint(base_url, self._resolver)
        request_id = str(uuid.uuid4())

        safe_context: dict[str, Any] = {}
        supplied_context = context if isinstance(context, dict) else {}
        for field in ("chain", "network", "chain_id"):
            value = supplied_context.get(field)
            if value is not None:
                safe_context[field] = value
        if manifest["permissions"].get("wallet_address") is True:
            wallet_address = supplied_context.get("wallet_address")
            if isinstance(wallet_address, str) and wallet_address.strip():
                safe_context["wallet_address"] = wallet_address.strip()

        request_payload = {
            "protocol_version": 1,
            "request_id": request_id,
            "connector": {
                "id": connector_id,
                "version": connector_version,
                **(
                    {"artifact_digest": manifest["artifact_digest"]}
                    if manifest.get("artifact_digest")
                    else {}
                ),
            },
            "tool": str(tool["connector_tool"]),
            "arguments": arguments,
            "context": safe_context,
        }

        owns_client = self._http_client is None
        client = self._http_client or httpx.AsyncClient(
            transport=_PinnedPublicAsyncTransport(self._resolver),
            follow_redirects=False,
            trust_env=False,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        try:
            try:
                response = await client.post(
                    f"{base_url}/invoke",
                    json=request_payload,
                    timeout=float(transport.get("timeout_ms", 10000)) / 1000.0,
                )
            except httpx.HTTPError as exc:
                raise ConnectorInvocationError(f"Connector request failed: {exc}") from exc
        finally:
            if owns_client:
                await client.aclose()

        if 300 <= response.status_code < 400:
            raise ConnectorInvocationError("Connector redirects are not allowed.")
        if response.status_code != 200:
            raise ConnectorInvocationError(f"Connector returned HTTP {response.status_code}.")
        if len(response.content) > MAX_CONNECTOR_RESPONSE_BYTES:
            raise ConnectorInvocationError("Connector response exceeds the size limit.")
        try:
            payload = response.json()
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ConnectorInvocationError("Connector response is not valid JSON.") from exc
        if not isinstance(payload, dict):
            raise ConnectorInvocationError("Connector response root must be an object.")
        if payload.get("protocol_version") != 1 or payload.get("request_id") != request_id:
            raise ConnectorInvocationError("Connector response binding is invalid.")
        response_connector = payload.get("connector")
        if not isinstance(response_connector, dict):
            raise ConnectorInvocationError("Connector response identity is missing.")
        if (
            response_connector.get("id") != connector_id
            or response_connector.get("version") != connector_version
        ):
            raise ConnectorInvocationError("Connector response identity does not match the request.")
        expected_artifact = manifest.get("artifact_digest")
        if expected_artifact and response_connector.get("artifact_digest") != expected_artifact:
            raise ConnectorInvocationError("Connector response artifact digest does not match.")
        if payload.get("tool") != tool["connector_tool"]:
            raise ConnectorInvocationError("Connector response tool does not match the request.")
        if payload.get("kind") != "read_result":
            raise ConnectorInvocationError("Read-only connector returned a non-read result.")
        _parse_expiry(payload.get("expires_at"))
        result = payload.get("result")
        _validate_json(result, tool["output_schema"], label="tool output")
        return {
            "connector_id": connector_id,
            "connector_version": connector_version,
            "tool": str(tool["connector_tool"]),
            "untrusted_external_data": True,
            "result": result,
            "expires_at": payload["expires_at"],
        }

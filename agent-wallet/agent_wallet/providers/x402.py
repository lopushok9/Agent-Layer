"""x402 discovery, preview, and buyer execution helpers."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from agent_wallet.config import resolve_solana_rpc_url
from agent_wallet.exceptions import ProviderError
from agent_wallet.http_client import get_client
from agent_wallet.wallet_layer.base import AgentWalletBackend

CDP_BAZAAR_DISCOVERY_BASE_URL = "https://api.cdp.coinbase.com/platform/v2/x402/discovery"
AGENTIC_MARKET_API_BASE_URL = "https://api.agentic.market/v1"
X402_EXECUTE_TIMEOUT_SECONDS = 45.0
SOLANA_CAIP_BY_NETWORK = {
    "mainnet": "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp",
    "devnet": "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1",
}
EVM_CAIP_BY_NETWORK = {
    "ethereum": "eip155:1",
    "base": "eip155:8453",
    "sepolia": "eip155:11155111",
    "base-sepolia": "eip155:84532",
}
_USDC_IDENTIFIERS = {
    "usdc",
    "usd coin",
    "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
    "0x036cbd53842c5426634e7929541ec2318f3dcf7e",
    "epjfwdd5aufqssqem2qn1xzybapc8g4wegkgkzwytdt1v",
}
log = logging.getLogger("agent_wallet.x402")


def _backend_chain(backend: AgentWalletBackend) -> str:
    chain = _trim(getattr(backend, "chain", "")).lower()
    if chain:
        return chain
    try:
        capabilities = backend.get_capabilities()
    except Exception:
        return ""
    return _trim(getattr(capabilities, "chain", "")).lower()


def _backend_network(backend: AgentWalletBackend) -> str:
    return _trim(getattr(backend, "network", "")).lower()


def _backend_solana_sdk_rpc_url(backend: AgentWalletBackend) -> str | None:
    candidates = getattr(backend, "rpc_urls", None)
    if isinstance(candidates, list):
        for candidate in candidates:
            text = _trim(candidate)
            if text.startswith(("http://", "https://")):
                return text
    primary = _trim(getattr(backend, "rpc_url", None))
    if primary.startswith(("http://", "https://")):
        return primary
    network = _backend_network(backend)
    fallback = resolve_solana_rpc_url(network or "mainnet", "")
    return _trim(fallback) or None


def _trim(value: Any) -> str:
    return str(value or "").strip()


def _canonical_json_text(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalize_discovery_provider(value: Any) -> str:
    provider = _trim(value).lower() or "auto"
    aliases = {
        "bazaar": "cdp_bazaar",
        "cdp": "cdp_bazaar",
        "agentic": "agentic_market",
        "agenticmarket": "agentic_market",
        "market": "agentic_market",
    }
    provider = aliases.get(provider, provider)
    if provider not in {"auto", "cdp_bazaar", "agentic_market"}:
        raise ProviderError("x402-discovery", f"Unsupported discovery provider: {provider}")
    return provider


def _normalize_http_method(value: Any) -> str:
    method = _trim(value).upper() or "GET"
    if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
        raise ProviderError("x402-http", f"Unsupported HTTP method: {method}")
    return method


def _normalize_headers(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ProviderError("x402-http", "headers must be an object when provided.")
    headers: dict[str, str] = {}
    for key, raw_value in value.items():
        name = _trim(key)
        if not name:
            raise ProviderError("x402-http", "headers must not contain empty names.")
        headers[name] = str(raw_value)
    return headers


def _normalize_query_params(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ProviderError("x402-http", "query must be an object when provided.")
    params: dict[str, str] = {}
    for key, raw_value in value.items():
        name = _trim(key)
        if not name:
            raise ProviderError("x402-http", "query must not contain empty names.")
        params[name] = str(raw_value)
    return params


def _append_query(url: str, query: dict[str, str]) -> str:
    if not query:
        return url
    parts = urlsplit(url)
    merged = dict(parse_qsl(parts.query, keep_blank_values=True))
    merged.update(query)
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(merged, doseq=True), parts.fragment)
    )


def _request_host(url: str) -> str:
    try:
        return _trim(urlsplit(url).netloc).lower()
    except Exception:
        return ""


def _response_text(response: Any) -> str:
    try:
        text = response.text
    except Exception:
        return ""
    return str(text or "")


def _parse_json_response(response: Any, *, provider: str, operation: str) -> Any:
    body = _response_text(response)
    if not body.strip():
        raise ProviderError(provider, f"{operation} returned an empty response body.")
    try:
        return response.json()
    except ValueError as exc:
        snippet = body.strip().replace("\n", " ")[:200]
        detail = f": {snippet}" if snippet else ""
        raise ProviderError(provider, f"{operation} returned invalid JSON{detail}") from exc


def _decode_payment_required(header_value: str) -> dict[str, Any]:
    raw = _trim(header_value)
    if not raw:
        raise ProviderError("x402-http", "PAYMENT-REQUIRED header is empty.")
    decoded_bytes: bytes | None = None
    for decoder in (base64.b64decode, base64.urlsafe_b64decode):
        try:
            padding = "=" * (-len(raw) % 4)
            decoded_bytes = decoder(raw + padding)
            break
        except Exception:
            continue
    if decoded_bytes is None:
        raise ProviderError("x402-http", "PAYMENT-REQUIRED header is not valid base64.")
    try:
        payload = json.loads(decoded_bytes.decode("utf-8"))
    except Exception as exc:
        raise ProviderError("x402-http", "PAYMENT-REQUIRED header is not valid JSON.") from exc
    if isinstance(payload, list):
        accepts = payload
        x402_version = None
    elif isinstance(payload, dict):
        accepts = payload.get("accepts")
        x402_version = payload.get("x402Version")
    else:
        raise ProviderError("x402-http", "PAYMENT-REQUIRED payload must decode to JSON.")
    if not isinstance(accepts, list) or not accepts:
        raise ProviderError("x402-http", "PAYMENT-REQUIRED payload does not contain accepts[].")
    return {
        "x402_version": x402_version,
        "accepts": accepts,
        "raw": payload,
        "encoded": raw,
    }


def _extract_requirement_extra(requirement: dict[str, Any]) -> dict[str, Any]:
    extra = requirement.get("extra")
    return dict(extra) if isinstance(extra, dict) else {}


def _requirement_field(requirement: Any, field_name: str) -> Any:
    if isinstance(requirement, dict):
        aliases = {
            "pay_to": ("pay_to", "payTo"),
            "max_timeout_seconds": ("max_timeout_seconds", "maxTimeoutSeconds"),
        }
        for candidate in aliases.get(field_name, (field_name,)):
            if candidate in requirement:
                return requirement.get(candidate)
        return None
    return getattr(requirement, field_name, None)


def _looks_like_usdc(requirement: dict[str, Any]) -> bool:
    asset = _trim(requirement.get("asset")).lower()
    if asset in _USDC_IDENTIFIERS:
        return True
    extra = _extract_requirement_extra(requirement)
    return _trim(extra.get("name")).lower() in _USDC_IDENTIFIERS


def _normalize_amount_hint(requirement: dict[str, Any]) -> str | None:
    amount = _trim(requirement.get("amount"))
    if not amount.isdigit():
        return None
    if _looks_like_usdc(requirement):
        raw = int(amount)
        whole = raw // 1_000_000
        fraction = raw % 1_000_000
        if fraction:
            return f"{whole}.{fraction:06d}".rstrip("0").rstrip(".")
        return f"{whole}"
    return None


def normalize_payment_requirement(
    requirement: dict[str, Any],
    *,
    source: str,
    resource_url: str | None = None,
) -> dict[str, Any]:
    extra = _extract_requirement_extra(requirement)
    amount = _trim(requirement.get("amount"))
    return {
        "scheme": _trim(requirement.get("scheme")).lower() or None,
        "network": _trim(requirement.get("network")) or None,
        "asset": _trim(requirement.get("asset")) or None,
        "amount": amount or None,
        "amount_display": _normalize_amount_hint(requirement),
        "pay_to": _trim(requirement.get("payTo")) or None,
        "max_timeout_seconds": requirement.get("maxTimeoutSeconds"),
        "resource_url": resource_url,
        "extra": extra,
        "source": source,
        "raw": requirement,
    }


def _normalize_cdp_resource(item: dict[str, Any]) -> dict[str, Any]:
    metadata = item.get("metadata")
    metadata_dict = dict(metadata) if isinstance(metadata, dict) else {}
    accepts = item.get("accepts") if isinstance(item.get("accepts"), list) else []
    resource = _trim(item.get("resource"))
    return {
        "discovery_provider": "cdp_bazaar",
        "resource": resource,
        "type": _trim(item.get("type")) or "http",
        "x402_version": item.get("x402Version"),
        "description": _trim(item.get("description") or metadata_dict.get("description")) or None,
        "last_updated": item.get("lastUpdated"),
        "accepts": [
            normalize_payment_requirement(requirement, source="cdp_bazaar", resource_url=resource)
            for requirement in accepts
            if isinstance(requirement, dict)
        ],
        "metadata": metadata_dict,
        "raw": item,
    }


def _normalize_agentic_service(service: dict[str, Any]) -> dict[str, Any]:
    endpoints = service.get("endpoints") if isinstance(service.get("endpoints"), list) else []
    normalized_endpoints: list[dict[str, Any]] = []
    accepts: list[dict[str, Any]] = []
    for endpoint in endpoints:
        if not isinstance(endpoint, dict):
            continue
        pricing = endpoint.get("pricing") if isinstance(endpoint.get("pricing"), dict) else {}
        normalized = {
            "url": _trim(endpoint.get("url")) or None,
            "description": _trim(endpoint.get("description")) or None,
            "method": _normalize_http_method(endpoint.get("method")),
            "pricing": {
                "amount": _trim(pricing.get("amount")) or None,
                "currency": _trim(pricing.get("currency")) or None,
                "network": _trim(pricing.get("network")) or None,
            },
        }
        normalized_endpoints.append(normalized)
        amount_text = _trim(pricing.get("amount"))
        currency = _trim(pricing.get("currency")).lower()
        network = _trim(pricing.get("network")).lower()
        if amount_text and currency == "usdc":
            accepts.append(
                {
                    "scheme": "exact",
                    "network": EVM_CAIP_BY_NETWORK.get(network, SOLANA_CAIP_BY_NETWORK.get(network, network)),
                    "asset": "USDC",
                    "amount": amount_text,
                    "amount_display": amount_text,
                    "pay_to": None,
                    "max_timeout_seconds": None,
                    "resource_url": normalized["url"],
                    "extra": {
                        "marketplace": "agentic_market",
                        "pricingCurrency": pricing.get("currency"),
                        "pricingNetwork": pricing.get("network"),
                    },
                    "source": "agentic_market",
                    "raw": endpoint,
                }
            )
    return {
        "discovery_provider": "agentic_market",
        "service_id": _trim(service.get("id")) or None,
        "service_name": _trim(service.get("name")) or None,
        "description": _trim(service.get("description")) or None,
        "domain": _trim(service.get("domain")) or None,
        "category": _trim(service.get("category")) or None,
        "networks": [str(item) for item in service.get("networks") or []],
        "integration_type": _trim(service.get("integrationType")) or None,
        "is_new": bool(service.get("isNew")),
        "endpoints": normalized_endpoints,
        "accepts": accepts,
        "raw": service,
    }


def _wallet_caip_networks(backend: AgentWalletBackend) -> list[str]:
    chain = _backend_chain(backend)
    network = _backend_network(backend)
    if chain == "evm":
        caip = EVM_CAIP_BY_NETWORK.get(network)
        return [caip] if caip else []
    if chain == "solana":
        caip = SOLANA_CAIP_BY_NETWORK.get(network)
        return [caip] if caip else []
    return []


def _solana_exact_execution_supported(backend: AgentWalletBackend) -> bool:
    return (
        _backend_chain(backend) == "solana"
        and _backend_network(backend) in {"mainnet", "devnet"}
        and getattr(backend, "signer", None) is not None
    )


def _evm_exact_execution_supported(backend: AgentWalletBackend) -> bool:
    return (
        _backend_chain(backend) == "evm"
        and _backend_network(backend) in {"base", "base-sepolia"}
        and callable(getattr(backend, "sign_x402_evm_exact_typed_data", None))
    )


def _evm_payment_requirement_supported(requirement: dict[str, Any]) -> bool:
    if _trim(requirement.get("scheme")).lower() != "exact":
        return False
    extra = _extract_requirement_extra(requirement)
    transfer_method = _trim(extra.get("assetTransferMethod")).lower()
    return transfer_method in {"", "eip3009", "transferwithauthorization"}


def _wallet_x402_support_summary(backend: AgentWalletBackend) -> dict[str, Any]:
    chain = _backend_chain(backend)
    network = _backend_network(backend)
    supported_networks = _wallet_caip_networks(backend)
    planned_execution_networks = {
        "eip155:8453",
        "eip155:84532",
        "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp",
        "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1",
    }
    execution_modes: list[str] = []
    if _solana_exact_execution_supported(backend):
        execution_modes.append("solana_exact")
    if _evm_exact_execution_supported(backend):
        execution_modes.append("evm_exact")
    return {
        "chain": chain,
        "network": network,
        "supported_caip_networks": supported_networks,
        "wallet_type_supported": chain in {"evm", "solana"},
        "execution_available": bool(execution_modes),
        "execution_modes": execution_modes,
        "planned_execution_networks": sorted(planned_execution_networks),
    }


def _requirement_compatibility(requirement: dict[str, Any], backend: AgentWalletBackend) -> dict[str, Any]:
    wallet_summary = _wallet_x402_support_summary(backend)
    network = _trim(requirement.get("network"))
    scheme = _trim(requirement.get("scheme")).lower()
    wallet_network_matches = network in wallet_summary["supported_caip_networks"]
    chain = _backend_chain(backend)
    planned_execution_supported = False
    currently_executable = False
    if chain == "solana":
        planned_execution_supported = scheme == "exact" and network in set(
            wallet_summary["planned_execution_networks"]
        )
        currently_executable = (
            planned_execution_supported
            and wallet_network_matches
            and _solana_exact_execution_supported(backend)
        )
    elif chain == "evm":
        planned_execution_supported = (
            scheme == "exact"
            and network in set(wallet_summary["planned_execution_networks"])
            and _evm_payment_requirement_supported(requirement)
        )
        currently_executable = (
            planned_execution_supported
            and wallet_network_matches
            and _evm_exact_execution_supported(backend)
        )
    if currently_executable:
        reason = (
            "Executable now through the local Solana exact buyer flow."
            if chain == "solana"
            else "Executable now through the local EVM exact buyer flow."
        )
    elif chain == "evm" and scheme == "exact" and not _evm_payment_requirement_supported(requirement):
        reason = "This EVM exact payment requires a transfer method that is not enabled in the current wallet runtime."
    elif planned_execution_supported and wallet_network_matches:
        reason = "Wallet network matches, but this backend does not yet expose a supported x402 signer path."
    elif planned_execution_supported:
        reason = "Planned execution path exists, but the requirement targets a different network than the active wallet."
    else:
        reason = "Unsupported scheme or network for the planned execution path."
    return {
        "wallet_type_supported": wallet_summary["wallet_type_supported"],
        "wallet_network_matches": wallet_network_matches,
        "planned_execution_supported": planned_execution_supported,
        "currently_executable": currently_executable,
        "reason": reason,
    }


def _select_preferred_requirement(
    requirements: list[dict[str, Any]],
    backend: AgentWalletBackend,
) -> dict[str, Any] | None:
    compatible = [
        requirement
        for requirement in requirements
        if _requirement_compatibility(requirement, backend)["planned_execution_supported"]
    ]
    exact_match = [
        requirement
        for requirement in compatible
        if _requirement_compatibility(requirement, backend)["wallet_network_matches"]
    ]
    candidates = exact_match or compatible
    if not candidates:
        return None

    def sort_key(item: dict[str, Any]) -> tuple[int, str]:
        amount = _trim(item.get("amount"))
        return (0 if amount.isdigit() else 1, amount)

    return sorted(candidates, key=sort_key)[0]


def _build_request_metadata(
    *,
    url: str,
    method: str = "GET",
    headers: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
    json_body: Any | None = None,
    text_body: str | None = None,
) -> dict[str, Any]:
    request_url = _trim(url)
    if not request_url:
        raise ProviderError("x402-http", "url is required.")
    http_method = _normalize_http_method(method)
    normalized_headers = _normalize_headers(headers)
    normalized_query = _normalize_query_params(query)
    if json_body is not None and text_body is not None:
        raise ProviderError("x402-http", "Provide either json_body or text_body, not both.")
    final_url = _append_query(request_url, normalized_query)
    body_hash = None
    content_type = None
    if json_body is not None:
        body_hash = _hash_text(_canonical_json_text(json_body))
        content_type = normalized_headers.get("Content-Type") or normalized_headers.get("content-type")
        if not content_type:
            normalized_headers["Content-Type"] = "application/json"
    elif text_body is not None:
        body_hash = _hash_text(text_body)
        content_type = normalized_headers.get("Content-Type") or normalized_headers.get("content-type")
    request_fingerprint = _hash_text(
        _canonical_json_text(
            {
                "method": http_method,
                "url": final_url,
                "body_hash": body_hash,
            }
        )
    )
    return {
        "url": final_url,
        "host": _request_host(final_url),
        "method": http_method,
        "headers": normalized_headers,
        "query": normalized_query,
        "json_body": json_body,
        "text_body": text_body,
        "body_hash": body_hash,
        "content_type": content_type,
        "request_fingerprint": request_fingerprint,
    }


async def _send_request(
    *,
    client: Any,
    request: dict[str, Any],
    extra_headers: dict[str, str] | None = None,
    timeout: float | None = None,
) -> Any:
    headers = dict(request["headers"])
    if extra_headers:
        headers.update(extra_headers)
    return await client.request(
        request["method"],
        request["url"],
        headers=headers,
        json=request["json_body"] if request["json_body"] is not None else None,
        content=request["text_body"] if request["text_body"] is not None else None,
        timeout=timeout,
    )


def _build_x402_action_payload(
    *,
    backend: AgentWalletBackend,
    request: dict[str, Any],
    wallet_summary: dict[str, Any],
    address: str | None,
    status_code: int,
    selected_payment: dict[str, Any] | None,
    accepted_payments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "asset_type": "x402-request",
        "source": "x402-http",
        "chain": _backend_chain(backend),
        "network": _backend_network(backend),
        "x402_network": selected_payment.get("network") if isinstance(selected_payment, dict) else None,
        "x402_scheme": selected_payment.get("scheme") if isinstance(selected_payment, dict) else None,
        "x402_asset": selected_payment.get("asset") if isinstance(selected_payment, dict) else None,
        "x402_amount": selected_payment.get("amount") if isinstance(selected_payment, dict) else None,
        "x402_amount_display": selected_payment.get("amount_display")
        if isinstance(selected_payment, dict)
        else None,
        "x402_pay_to": selected_payment.get("pay_to") if isinstance(selected_payment, dict) else None,
        "request_url": request["url"],
        "method": request["method"],
        "request_fingerprint": request["request_fingerprint"],
        "body_hash": request["body_hash"],
        "content_type": request["content_type"],
        "wallet": {
            **wallet_summary,
            "address": address,
        },
        "status_code": status_code,
        "selected_payment": selected_payment,
        "accepted_payments": accepted_payments,
        "payment_required": selected_payment is not None,
    }


def _response_preview(response: Any) -> Any:
    try:
        return response.json()
    except Exception:
        return _response_text(response)[:2000]


def _parse_payment_required_response(
    response: Any,
    *,
    backend: AgentWalletBackend,
    request: dict[str, Any],
    address: str | None,
    wallet_summary: dict[str, Any],
) -> dict[str, Any]:
    payment_required = response.headers.get("PAYMENT-REQUIRED")
    if not payment_required:
        raise ProviderError(
            "x402-http",
            "Server returned HTTP 402 without a PAYMENT-REQUIRED header.",
            details={"status_code": response.status_code, "url": request["url"]},
        )

    decoded = _decode_payment_required(payment_required)
    normalized_accepts = [
        normalize_payment_requirement(requirement, source="payment_required", resource_url=request["url"])
        for requirement in decoded["accepts"]
        if isinstance(requirement, dict)
    ]
    compatibility = [
        {
            **requirement,
            "compatibility": _requirement_compatibility(requirement, backend),
        }
        for requirement in normalized_accepts
    ]
    selected = _select_preferred_requirement(normalized_accepts, backend)
    preview = _build_x402_action_payload(
        backend=backend,
        request=request,
        wallet_summary=wallet_summary,
        address=address,
        status_code=response.status_code,
        selected_payment=selected,
        accepted_payments=compatibility,
    )
    preview.update(
        {
            "execute_available": bool(
                isinstance(selected, dict)
                and _requirement_compatibility(selected, backend)["currently_executable"]
            ),
            "x402_version": decoded["x402_version"],
            "response_headers": {
                "payment-required": decoded["encoded"],
                "content-type": response.headers.get("content-type"),
            },
        }
    )
    return preview


def _require_executable_payment(
    *,
    preview: dict[str, Any],
    backend: AgentWalletBackend,
) -> dict[str, Any]:
    selected = preview.get("selected_payment")
    if not isinstance(selected, dict):
        raise ProviderError(
            "x402-http",
            "No compatible x402 payment requirement was selected for this wallet.",
            details={
                "request_url": preview.get("request_url"),
                "accepted_payments": preview.get("accepted_payments"),
            },
        )
    compatibility = _requirement_compatibility(selected, backend)
    if not compatibility["currently_executable"]:
        raise ProviderError(
            "x402-http",
            str(compatibility["reason"]),
            details={
                "selected_payment": selected,
                "compatibility": compatibility,
            },
        )
    return selected


def _validate_payment_requirement(
    selected: dict[str, Any] | None,
    *,
    backend: AgentWalletBackend,
    request_url: str,
) -> dict[str, Any]:
    if not isinstance(selected, dict):
        raise ProviderError(
            "x402-validate",
            "This endpoint returned HTTP 402 but no compatible payment option was found for the active wallet.",
            details={
                "request_url": request_url,
                "wallet_chain": _backend_chain(backend),
                "wallet_network": _backend_network(backend),
            },
        )

    scheme = _trim(selected.get("scheme")).lower()
    if scheme != "exact":
        raise ProviderError(
            "x402-validate",
            f"Unsupported x402 payment scheme '{scheme or 'unknown'}'. Only 'exact' is supported.",
            details={"request_url": request_url, "selected_payment": selected},
        )

    if not _trim(selected.get("pay_to")):
        raise ProviderError(
            "x402-validate",
            "Payment destination (payTo) is missing from the x402 requirement.",
            details={"request_url": request_url, "selected_payment": selected},
        )

    compatibility = _requirement_compatibility(selected, backend)
    if compatibility["currently_executable"]:
        return selected

    chain = _backend_chain(backend) or "unknown"
    network = _backend_network(backend) or "unknown"
    requirement_network = _trim(selected.get("network")) or "unknown"
    if chain == "solana" and requirement_network not in SOLANA_CAIP_BY_NETWORK.values():
        message = (
            f"This endpoint requires payment on {requirement_network}, but the active wallet is Solana ({network})."
        )
    elif chain == "evm" and requirement_network not in EVM_CAIP_BY_NETWORK.values():
        message = (
            f"This endpoint requires payment on {requirement_network}, but the active wallet is EVM ({network})."
        )
    else:
        message = str(compatibility["reason"])

    raise ProviderError(
        "x402-validate",
        message,
        details={
            "request_url": request_url,
            "selected_payment": selected,
            "compatibility": compatibility,
        },
    )


def _validate_request_execution_policy(
    *,
    request: dict[str, Any],
    backend: AgentWalletBackend,
) -> None:
    host = _trim(request.get("host")).lower()
    if host == "x402.alchemy.com":
        headers = request.get("headers")
        has_auth = isinstance(headers, dict) and any(
            str(key).strip().lower() == "authorization" and str(value).strip()
            for key, value in headers.items()
        )
        if not has_auth:
            raise ProviderError(
                "x402-validate",
                (
                    "Alchemy's x402 gateway needs wallet-auth headers in addition to the payment challenge. "
                    "The generic x402 tool does not mint Alchemy SIWE/SIWS auth tokens yet, so this endpoint "
                    "is not safe to execute through the generic flow."
                ),
                details={
                    "request_url": request.get("url"),
                    "host": host,
                    "wallet_chain": _backend_chain(backend),
                    "wallet_network": _backend_network(backend),
                    "hint": "Use a dedicated Alchemy agent gateway integration or authenticated CLI flow.",
                },
            )

def _select_sdk_payment_requirement(
    payment_required: Any,
    *,
    selected_payment: dict[str, Any],
) -> Any:
    accepts = getattr(payment_required, "accepts", None)
    if not isinstance(accepts, list) or not accepts:
        raise ProviderError("x402-http", "Decoded x402 payment payload does not contain accepts[].")

    selected_raw = selected_payment.get("raw") if isinstance(selected_payment, dict) else None
    if isinstance(selected_raw, dict):
        for requirement in accepts:
            model_dump = getattr(requirement, "model_dump", None)
            if callable(model_dump):
                dumped = model_dump(by_alias=True, exclude_none=True)
                if dumped == selected_raw:
                    return requirement

    for requirement in accepts:
        if (
            _trim(_requirement_field(requirement, "scheme")).lower()
            == _trim(selected_payment.get("scheme")).lower()
            and _trim(_requirement_field(requirement, "network"))
            == _trim(selected_payment.get("network"))
            and _trim(_requirement_field(requirement, "asset"))
            == _trim(selected_payment.get("asset"))
            and _trim(_requirement_field(requirement, "amount"))
            == _trim(selected_payment.get("amount"))
            and _trim(_requirement_field(requirement, "pay_to"))
            == _trim(selected_payment.get("pay_to"))
        ):
            return requirement

    if len(accepts) == 1:
        return accepts[0]

    raise ProviderError(
        "x402-http",
        "Could not match the selected x402 payment back to the decoded PAYMENT-REQUIRED payload.",
        details={
            "selected_payment": selected_payment,
            "accepts_count": len(accepts),
        },
    )


def _build_selected_payment_required_payload(
    payment_required: Any,
    *,
    selected_payment: dict[str, Any],
) -> Any:
    selected_requirement = _select_sdk_payment_requirement(
        payment_required,
        selected_payment=selected_payment,
    )
    return payment_required.model_copy(update={"accepts": [selected_requirement]})


def _load_x402_common_sdk() -> dict[str, Any]:
    try:
        from x402 import x402Client
        from x402.http.x402_http_client_base import x402HTTPClientBase
        from x402.http.utils import decode_payment_required_header
    except ImportError as exc:
        raise ProviderError(
            "x402-sdk",
            "x402 execution requires the x402 Python package with HTTP client support.",
            details={"hint": 'Install dependencies so `x402[httpx]` is available in the wallet runtime.'},
        ) from exc
    return {
        "x402Client": x402Client,
        "x402HTTPClientBase": x402HTTPClientBase,
        "decode_payment_required_header": decode_payment_required_header,
    }


def _load_x402_solana_sdk() -> dict[str, Any]:
    sdk = _load_x402_common_sdk()
    try:
        from x402.mechanisms.svm.exact import register_exact_svm_client
    except ImportError as exc:
        raise ProviderError(
            "x402-sdk",
            "x402 Solana execution requires SVM support.",
            details={"hint": 'Install dependencies so `x402[httpx,svm]` is available in the wallet runtime.'},
        ) from exc
    sdk.update(
        {
            "register_exact_svm_client": register_exact_svm_client,
        }
    )
    return sdk


def _load_x402_evm_sdk() -> dict[str, Any]:
    sdk = _load_x402_common_sdk()
    try:
        from x402.mechanisms.evm.exact import register_exact_evm_client
    except ImportError as exc:
        raise ProviderError(
            "x402-sdk",
            "x402 EVM execution requires EVM support.",
            details={"hint": 'Install dependencies so `x402[httpx,evm]` is available in the wallet runtime.'},
        ) from exc
    sdk.update(
        {
            "register_exact_evm_client": register_exact_evm_client,
        }
    )
    return sdk


def _load_x402_sdk() -> dict[str, Any]:
    return _load_x402_common_sdk()


def _build_solana_sdk_signer(backend: AgentWalletBackend) -> Any:
    signer = getattr(backend, "signer", None)
    if signer is None or not hasattr(signer, "export_keypair_bytes"):
        raise ProviderError(
            "x402-solana",
            "The active Solana backend does not expose a local signer for x402 payments.",
        )
    try:
        from solders.keypair import Keypair
    except ImportError as exc:
        raise ProviderError(
            "x402-solana",
            "Solders is required for Solana x402 signing.",
        ) from exc

    class _OpenClawSolanaX402Signer:
        def __init__(self, wallet_signer: Any):
            self._wallet_signer = wallet_signer
            self._keypair = Keypair.from_bytes(wallet_signer.export_keypair_bytes())

        @property
        def address(self) -> str:
            return str(self._wallet_signer.address)

        @property
        def keypair(self) -> Any:
            return self._keypair

        def sign_transaction(self, tx: Any) -> Any:
            tx.sign([self._keypair])
            return tx

    return _OpenClawSolanaX402Signer(signer)


def _build_evm_sdk_signer(backend: AgentWalletBackend, address: str) -> Any:
    sign_typed_data = getattr(backend, "sign_x402_evm_exact_typed_data", None)
    if not callable(sign_typed_data):
        raise ProviderError(
            "x402-evm",
            "The active EVM backend does not expose an x402 exact typed-data signer.",
        )

    class _OpenClawEvmX402Signer:
        def __init__(self, wallet_backend: AgentWalletBackend, wallet_address: str):
            self._wallet_backend = wallet_backend
            self._address = wallet_address

        @property
        def address(self) -> str:
            return self._address

        def sign_typed_data(
            self,
            domain: Any,
            types: dict[str, list[Any]],
            primary_type: str,
            message: dict[str, Any],
        ) -> bytes:
            normalized_types: dict[str, list[dict[str, str]]] = {}
            for type_name, fields in types.items():
                normalized_types[type_name] = [
                    {
                        "name": _trim(getattr(field, "name", "")),
                        "type": _trim(getattr(field, "type", "")),
                    }
                    for field in fields
                ]
            domain_payload = {
                "name": getattr(domain, "name", None),
                "version": getattr(domain, "version", None),
                "chainId": getattr(domain, "chain_id", None),
                "verifyingContract": getattr(domain, "verifying_contract", None),
            }
            return self._wallet_backend.sign_x402_evm_exact_typed_data(
                domain=domain_payload,
                types=normalized_types,
                primary_type=primary_type,
                message=message,
            )

    return _OpenClawEvmX402Signer(backend, address)


async def _create_payment_headers(
    *,
    backend: AgentWalletBackend,
    payment_required_header: str,
    selected_payment: dict[str, Any],
) -> dict[str, str]:
    chain = _backend_chain(backend)
    if chain == "solana":
        sdk = _load_x402_solana_sdk()
        payment_required = sdk["decode_payment_required_header"](payment_required_header)
        selected_payload = _build_selected_payment_required_payload(
            payment_required,
            selected_payment=selected_payment,
        )
        client = sdk["x402Client"]()
        sdk_rpc_url = _backend_solana_sdk_rpc_url(backend)
        if not sdk_rpc_url:
            raise ProviderError(
                "x402-solana",
                "No direct Solana RPC URL is available for the x402 SDK signer path.",
                details={"network": _backend_network(backend)},
            )
        sdk["register_exact_svm_client"](
            client,
            _build_solana_sdk_signer(backend),
            networks=str(selected_payment["network"]),
            rpc_url=sdk_rpc_url,
        )
        try:
            payment_payload = await client.create_payment_payload(selected_payload)
        except Exception as exc:
            raise ProviderError(
                "x402-solana",
                "Failed to build the Solana x402 payment payload.",
                details={
                    "network": _backend_network(backend),
                    "sdk_rpc_url": sdk_rpc_url,
                    "error_type": type(exc).__name__,
                    "error": str(exc) or None,
                },
            ) from exc
        return sdk["x402HTTPClientBase"]().encode_payment_signature_header(payment_payload)

    if chain == "evm":
        sdk = _load_x402_evm_sdk()
        payment_required = sdk["decode_payment_required_header"](payment_required_header)
        selected_payload = _build_selected_payment_required_payload(
            payment_required,
            selected_payment=selected_payment,
        )
        client = sdk["x402Client"]()
        address = await backend.get_address()
        if not isinstance(address, str) or not address.strip():
            raise ProviderError("x402-evm", "The active EVM backend did not resolve a payer address.")
        sdk["register_exact_evm_client"](
            client,
            _build_evm_sdk_signer(backend, address.strip()),
            networks=str(selected_payment["network"]),
        )
        payment_payload = await client.create_payment_payload(selected_payload)
        return sdk["x402HTTPClientBase"]().encode_payment_signature_header(payment_payload)

    raise ProviderError(
        "x402-http",
        "Only Solana and EVM buyer flows are executable in this milestone.",
        details={"chain": chain},
    )


def _extract_settlement_header(response: Any) -> dict[str, Any]:
    sdk = _load_x402_sdk()
    settle = sdk["x402HTTPClientBase"]().get_payment_settle_response(
        lambda name: response.headers.get(name)
    )
    return settle.model_dump(by_alias=True, exclude_none=True)


def _extract_settlement_header_safe(response: Any) -> dict[str, Any] | None:
    try:
        return _extract_settlement_header(response)
    except Exception as exc:
        log.warning(
            "x402 settlement header parse failed",
            extra={
                "status_code": getattr(response, "status_code", None),
                "payment_response": response.headers.get("PAYMENT-RESPONSE")
                if hasattr(response, "headers")
                else None,
                "x_payment_response": response.headers.get("X-PAYMENT-RESPONSE")
                if hasattr(response, "headers")
                else None,
                "error_type": type(exc).__name__,
                "error": str(exc) or None,
            },
        )
        return None


def _log_x402_execute(
    *,
    request: dict[str, Any],
    selected_payment: dict[str, Any] | None,
    response: Any,
    settlement: dict[str, Any] | None,
) -> None:
    log.info(
        "x402 execute completed",
        extra={
            "url": request.get("url"),
            "method": request.get("method"),
            "request_fingerprint": request.get("request_fingerprint"),
            "x402_network": selected_payment.get("network") if isinstance(selected_payment, dict) else None,
            "x402_asset": selected_payment.get("asset") if isinstance(selected_payment, dict) else None,
            "x402_amount": selected_payment.get("amount") if isinstance(selected_payment, dict) else None,
            "x402_pay_to": selected_payment.get("pay_to") if isinstance(selected_payment, dict) else None,
            "status_code": getattr(response, "status_code", None),
            "transaction": settlement.get("transaction") if isinstance(settlement, dict) else None,
            "confirmed": bool(settlement and settlement.get("success")),
        },
    )


async def search_services(
    *,
    query: str | None = None,
    discovery_provider: str = "auto",
    network: str | None = None,
    asset: str | None = None,
    scheme: str | None = None,
    max_usd_price: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    provider = _normalize_discovery_provider(discovery_provider)
    if provider == "auto":
        provider = "cdp_bazaar"
    if limit <= 0:
        raise ProviderError("x402-discovery", "limit must be greater than zero.")
    client = get_client()

    if provider == "cdp_bazaar":
        if query and _trim(query):
            response = await client.get(
                f"{CDP_BAZAAR_DISCOVERY_BASE_URL}/search",
                params={
                    "query": _trim(query),
                    "network": _trim(network) or None,
                    "asset": _trim(asset) or None,
                    "scheme": _trim(scheme) or None,
                    "maxUsdPrice": _trim(max_usd_price) or None,
                    "limit": min(limit, 20),
                },
            )
            payload = _parse_json_response(
                response, provider="x402-cdp-bazaar", operation="CDP Bazaar search"
            )
            resources = payload.get("resources") if isinstance(payload, dict) else None
            if not isinstance(resources, list):
                raise ProviderError("x402-cdp-bazaar", "Unexpected CDP Bazaar search response.")
            items = [_normalize_cdp_resource(item) for item in resources if isinstance(item, dict)]
            return {
                "discovery_provider": provider,
                "query": _trim(query),
                "count": len(items),
                "partial_results": bool(payload.get("partialResults")),
                "search_method": payload.get("searchMethod"),
                "items": items,
            }

        response = await client.get(
            f"{CDP_BAZAAR_DISCOVERY_BASE_URL}/resources",
            params={"type": "http", "limit": min(limit, 1000), "offset": 0},
        )
        payload = _parse_json_response(
            response, provider="x402-cdp-bazaar", operation="CDP Bazaar resources"
        )
        resources = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(resources, list):
            raise ProviderError("x402-cdp-bazaar", "Unexpected CDP Bazaar resources response.")
        items = [_normalize_cdp_resource(item) for item in resources if isinstance(item, dict)]
        return {
            "discovery_provider": provider,
            "query": "",
            "count": len(items),
            "pagination": payload.get("pagination") if isinstance(payload, dict) else None,
            "items": items,
        }

    endpoint = "/services/search" if query and _trim(query) else "/services/"
    params = {"q": _trim(query)} if query and _trim(query) else None
    response = await client.get(f"{AGENTIC_MARKET_API_BASE_URL}{endpoint}", params=params)
    payload = _parse_json_response(
        response, provider="x402-agentic-market", operation="Agentic Market search"
    )
    services = payload.get("services") if isinstance(payload, dict) else None
    if not isinstance(services, list):
        raise ProviderError("x402-agentic-market", "Unexpected Agentic Market response.")
    normalized = [
        _normalize_agentic_service(service)
        for service in services
        if isinstance(service, dict)
    ]
    if network:
        needle = _trim(network).lower()
        normalized = [
            item
            for item in normalized
            if needle in {entry.lower() for entry in item.get("networks") or []}
        ]
    if scheme:
        needle = _trim(scheme).lower()
        normalized = [
            item
            for item in normalized
            if any(_trim(req.get("scheme")).lower() == needle for req in item.get("accepts") or [])
        ]
    if asset:
        needle = _trim(asset).lower()
        normalized = [
            item
            for item in normalized
            if any(_trim(req.get("asset")).lower() == needle for req in item.get("accepts") or [])
        ]
    return {
        "discovery_provider": provider,
        "query": _trim(query),
        "count": len(normalized[:limit]),
        "items": normalized[:limit],
    }


async def get_service_details(
    *,
    reference: str,
    discovery_provider: str = "auto",
) -> dict[str, Any]:
    ref = _trim(reference)
    if not ref:
        raise ProviderError("x402-discovery", "reference is required.")
    provider = _normalize_discovery_provider(discovery_provider)
    if provider == "auto":
        provider = (
            "cdp_bazaar" if ref.startswith("http://") or ref.startswith("https://") else "agentic_market"
        )

    if provider == "cdp_bazaar":
        resources = await search_services(discovery_provider="cdp_bazaar", limit=200)
        exact = next((item for item in resources["items"] if item.get("resource") == ref), None)
        if exact is None:
            needle = ref.lower()
            exact = next(
                (
                    item
                    for item in resources["items"]
                    if needle in _trim(item.get("resource")).lower()
                    or needle in _trim(item.get("description")).lower()
                ),
                None,
            )
        if exact is None:
            raise ProviderError("x402-cdp-bazaar", f"No Bazaar resource matched: {ref}")
        return {"discovery_provider": provider, "service": exact}

    query = ref
    if ref.startswith("http://") or ref.startswith("https://"):
        query = urlsplit(ref).netloc or ref
    services = await search_services(query=query, discovery_provider="agentic_market", limit=20)
    needle = ref.lower()
    exact = next(
        (
            item
            for item in services["items"]
            if needle
            in {
                _trim(item.get("service_id")).lower(),
                _trim(item.get("domain")).lower(),
                _trim(item.get("service_name")).lower(),
            }
        ),
        None,
    )
    if exact is None and services["items"]:
        exact = services["items"][0]
    if exact is None:
        raise ProviderError("x402-agentic-market", f"No Agentic Market service matched: {ref}")
    return {"discovery_provider": provider, "service": exact}


async def preview_request(
    *,
    backend: AgentWalletBackend,
    url: str,
    method: str = "GET",
    headers: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
    json_body: Any | None = None,
    text_body: str | None = None,
) -> dict[str, Any]:
    request = _build_request_metadata(
        url=url,
        method=method,
        headers=headers,
        query=query,
        json_body=json_body,
        text_body=text_body,
    )
    client = get_client()
    response = await _send_request(client=client, request=request)
    wallet_summary = _wallet_x402_support_summary(backend)
    address = await backend.get_address()
    preview: dict[str, Any] = {
        "mode": "preview",
        **_build_x402_action_payload(
            backend=backend,
            request=request,
            wallet_summary=wallet_summary,
            address=address,
            status_code=response.status_code,
            selected_payment=None,
        ),
        "execute_available": False,
        "request": {
            "url": request["url"],
            "method": request["method"],
            "request_fingerprint": request["request_fingerprint"],
            "query": request["query"],
            "body_hash": request["body_hash"],
            "content_type": request["content_type"],
        },
    }

    if response.status_code != 402:
        preview.update(
            {
                "payment_required": False,
                "response_preview": _response_preview(response),
                "response_headers": {
                    "content-type": response.headers.get("content-type"),
                },
            }
        )
        return preview

    payment_preview = _parse_payment_required_response(
        response,
        backend=backend,
        request=request,
        address=address,
        wallet_summary=wallet_summary,
    )
    payment_preview["mode"] = "preview"
    payment_preview["request"] = {
        "url": request["url"],
        "method": request["method"],
        "request_fingerprint": request["request_fingerprint"],
        "query": request["query"],
        "body_hash": request["body_hash"],
        "content_type": request["content_type"],
    }
    return payment_preview


async def prepare_request(
    *,
    backend: AgentWalletBackend,
    url: str,
    method: str = "GET",
    headers: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
    json_body: Any | None = None,
    text_body: str | None = None,
) -> dict[str, Any]:
    preview = await preview_request(
        backend=backend,
        url=url,
        method=method,
        headers=headers,
        query=query,
        json_body=json_body,
        text_body=text_body,
    )
    if not preview.get("payment_required"):
        prepared = dict(preview)
        prepared["mode"] = "prepare"
        prepared["prepared"] = False
        prepared["prepare_note"] = "The endpoint did not require x402 payment for this request."
        return prepared

    selected_payment = _require_executable_payment(preview=preview, backend=backend)
    payment_required_header = (
        dict(preview.get("response_headers") or {}).get("payment-required")
    )
    if not isinstance(payment_required_header, str) or not payment_required_header.strip():
        raise ProviderError("x402-http", "Missing PAYMENT-REQUIRED header in preview state.")
    # Create the payload once during prepare to validate that the active wallet can sign it.
    await _create_payment_headers(
        backend=backend,
        payment_required_header=payment_required_header,
        selected_payment=selected_payment,
    )
    prepared = dict(preview)
    prepared["mode"] = "prepare"
    prepared["prepared"] = True
    prepared["signed"] = False
    prepared["broadcasted"] = False
    prepared["confirmed"] = False
    prepared["payment_payload_withheld"] = True
    prepared["prepare_note"] = (
        "x402 payment authorization was validated locally, but the PAYMENT-SIGNATURE header is withheld until execute."
    )
    return prepared


async def execute_request(
    *,
    backend: AgentWalletBackend,
    url: str,
    method: str = "GET",
    headers: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
    json_body: Any | None = None,
    text_body: str | None = None,
) -> dict[str, Any]:
    executed = await pay_and_fetch(
        backend=backend,
        url=url,
        method=method,
        headers=headers,
        query=query,
        json_body=json_body,
        text_body=text_body,
    )
    executed["mode"] = "execute"
    return executed


async def pay_and_fetch(
    *,
    backend: AgentWalletBackend,
    url: str,
    method: str = "GET",
    headers: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
    json_body: Any | None = None,
    text_body: str | None = None,
) -> dict[str, Any]:
    preview = await preview_request(
        backend=backend,
        url=url,
        method=method,
        headers=headers,
        query=query,
        json_body=json_body,
        text_body=text_body,
    )
    if not preview.get("payment_required"):
        executed = dict(preview)
        executed["mode"] = "execute"
        executed["paid"] = False
        executed["broadcasted"] = False
        executed["confirmed"] = False
        return executed

    selected_payment = _validate_payment_requirement(
        preview.get("selected_payment")
        if isinstance(preview.get("selected_payment"), dict)
        else None,
        backend=backend,
        request_url=str(preview.get("request_url") or url),
    )
    payment_required_header = (
        dict(preview.get("response_headers") or {}).get("payment-required")
    )
    if not isinstance(payment_required_header, str) or not payment_required_header.strip():
        raise ProviderError("x402-http", "Missing PAYMENT-REQUIRED header in preview state.")

    request = _build_request_metadata(
        url=url,
        method=method,
        headers=headers,
        query=query,
        json_body=json_body,
        text_body=text_body,
    )
    _validate_request_execution_policy(request=request, backend=backend)
    payment_headers = await _create_payment_headers(
        backend=backend,
        payment_required_header=payment_required_header,
        selected_payment=selected_payment,
    )
    client = get_client()
    response = await _send_request(
        client=client,
        request=request,
        extra_headers=payment_headers,
        timeout=X402_EXECUTE_TIMEOUT_SECONDS,
    )
    settlement = _extract_settlement_header_safe(response)
    _log_x402_execute(
        request=request,
        selected_payment=selected_payment,
        response=response,
        settlement=settlement,
    )

    executed = dict(preview)
    executed.update(
        {
            "mode": "execute",
            "paid": True,
            "broadcasted": bool(settlement and settlement.get("transaction")),
            "confirmed": bool(settlement and settlement.get("success")),
            "payment_settlement": settlement,
            "status_code": response.status_code,
            "response_preview": _response_preview(response),
            "response_headers": {
                "content-type": response.headers.get("content-type"),
                "payment-response": response.headers.get("PAYMENT-RESPONSE")
                or response.headers.get("X-PAYMENT-RESPONSE"),
            },
        }
    )
    if response.status_code == 402:
        raise ProviderError(
            "x402-http",
            "The paid x402 retry still returned HTTP 402.",
            details={
                "request_url": request["url"],
                "selected_payment": selected_payment,
                "response_preview": executed["response_preview"],
            },
        )
    return executed

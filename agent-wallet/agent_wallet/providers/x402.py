"""x402 discovery and preview helpers."""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from agent_wallet.exceptions import ProviderError
from agent_wallet.http_client import get_client
from agent_wallet.wallet_layer.base import AgentWalletBackend

CDP_BAZAAR_DISCOVERY_BASE_URL = "https://api.cdp.coinbase.com/platform/v2/x402/discovery"
AGENTIC_MARKET_API_BASE_URL = "https://api.agentic.market/v1"
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
    chain = _trim(getattr(backend, "chain", "")).lower()
    network = _trim(getattr(backend, "network", "")).lower()
    if chain == "evm":
        caip = EVM_CAIP_BY_NETWORK.get(network)
        return [caip] if caip else []
    if chain == "solana":
        caip = SOLANA_CAIP_BY_NETWORK.get(network)
        return [caip] if caip else []
    return []


def _wallet_x402_support_summary(backend: AgentWalletBackend) -> dict[str, Any]:
    chain = _trim(getattr(backend, "chain", "")).lower()
    network = _trim(getattr(backend, "network", "")).lower()
    supported_networks = _wallet_caip_networks(backend)
    planned_execution_networks = {
        "eip155:8453",
        "eip155:84532",
        "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp",
        "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1",
    }
    return {
        "chain": chain,
        "network": network,
        "supported_caip_networks": supported_networks,
        "wallet_type_supported": chain in {"evm", "solana"},
        "execution_available": False,
        "planned_execution_networks": sorted(planned_execution_networks),
    }


def _requirement_compatibility(requirement: dict[str, Any], backend: AgentWalletBackend) -> dict[str, Any]:
    wallet_summary = _wallet_x402_support_summary(backend)
    network = _trim(requirement.get("network"))
    scheme = _trim(requirement.get("scheme")).lower()
    wallet_network_matches = network in wallet_summary["supported_caip_networks"]
    planned_execution_supported = (
        scheme == "exact" and network in set(wallet_summary["planned_execution_networks"])
    )
    return {
        "wallet_type_supported": wallet_summary["wallet_type_supported"],
        "wallet_network_matches": wallet_network_matches,
        "planned_execution_supported": planned_execution_supported,
        "currently_executable": False,
        "reason": (
            "Execution path is not wired yet in this milestone."
            if planned_execution_supported
            else "Unsupported scheme or network for the planned execution path."
        ),
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

    client = get_client()
    response = await client.request(
        http_method,
        final_url,
        headers=normalized_headers,
        json=json_body if json_body is not None else None,
        content=text_body if text_body is not None else None,
    )
    wallet_summary = _wallet_x402_support_summary(backend)
    preview: dict[str, Any] = {
        "mode": "preview",
        "execute_available": False,
        "request": {
            "url": final_url,
            "method": http_method,
            "request_fingerprint": request_fingerprint,
            "query": normalized_query,
            "body_hash": body_hash,
            "content_type": content_type,
        },
        "wallet": {
            **wallet_summary,
            "address": await backend.get_address(),
        },
        "status_code": response.status_code,
    }

    if response.status_code != 402:
        body_preview: Any
        try:
            body_preview = response.json()
        except Exception:
            body_preview = _response_text(response)[:1000]
        preview.update(
            {
                "payment_required": False,
                "response_preview": body_preview,
                "response_headers": {
                    "content-type": response.headers.get("content-type"),
                },
            }
        )
        return preview

    payment_required = response.headers.get("PAYMENT-REQUIRED")
    if not payment_required:
        raise ProviderError(
            "x402-http",
            "Server returned HTTP 402 without a PAYMENT-REQUIRED header.",
            details={"status_code": response.status_code, "url": final_url},
        )

    decoded = _decode_payment_required(payment_required)
    normalized_accepts = [
        normalize_payment_requirement(requirement, source="payment_required", resource_url=final_url)
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
    preview.update(
        {
            "payment_required": True,
            "x402_version": decoded["x402_version"],
            "accepted_payments": compatibility,
            "selected_payment": selected,
            "confirmation_summary": {
                "operation": "x402 paid request preview",
                "request_url": final_url,
                "method": http_method,
                "request_fingerprint": request_fingerprint,
                "selected_network": selected.get("network") if isinstance(selected, dict) else None,
                "selected_asset": selected.get("asset") if isinstance(selected, dict) else None,
                "selected_amount": selected.get("amount") if isinstance(selected, dict) else None,
                "selected_amount_display": selected.get("amount_display") if isinstance(selected, dict) else None,
                "selected_pay_to": selected.get("pay_to") if isinstance(selected, dict) else None,
            },
            "response_headers": {
                "payment-required": decoded["encoded"],
                "content-type": response.headers.get("content-type"),
            },
        }
    )
    return preview

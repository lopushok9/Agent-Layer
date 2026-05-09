"""Houdini private swap provider helpers."""

from __future__ import annotations

import os
import time
from decimal import Decimal, InvalidOperation
from typing import Any

from agent_wallet.config import settings
from agent_wallet.exceptions import ProviderError
from agent_wallet.http_client import get_client

_TOKEN_CACHE_TTL_SECONDS = 24 * 60 * 60
_CEX_TOKEN_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_SOLANA_NATIVE_ALIASES = {"sol", "native", "solana"}


def _gateway_base_url() -> str:
    return os.getenv("PROVIDER_GATEWAY_URL", settings.provider_gateway_url).strip().rstrip("/")


def _gateway_enabled() -> bool:
    return bool(_gateway_base_url())


def _gateway_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "x-user-agent": settings.houdini_user_agent.strip() or "AgentLayer/0.1.12",
        "x-user-timezone": settings.houdini_user_timezone.strip() or "UTC",
    }
    bearer = os.getenv(
        "PROVIDER_GATEWAY_BEARER_TOKEN",
        settings.provider_gateway_bearer_token,
    ).strip()
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    return headers


def _base_url() -> str:
    return settings.houdini_api_base_url.rstrip("/")


def _direct_houdini_enabled() -> bool:
    return bool(settings.houdini_api_key.strip() and settings.houdini_api_secret.strip())


def _gateway_route_missing(status_code: int, payload: Any) -> bool:
    if status_code == 404:
        return True
    if isinstance(payload, dict):
        message = str(payload.get("error") or "").lower()
        if "not found" in message:
            return True
    return False


def _normalize_error(payload: Any) -> str:
    if isinstance(payload, dict):
        message = payload.get("message") or payload.get("error") or payload.get("detail")
        if message:
            return str(message)
    return "Houdini request failed."


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
        raise ProviderError(
            provider,
            f"{operation} returned invalid JSON{detail}",
        ) from exc


def _require_compliance_headers() -> dict[str, str]:
    api_key = settings.houdini_api_key.strip()
    api_secret = settings.houdini_api_secret.strip()
    if not api_key or not api_secret:
        raise ProviderError(
            "houdini",
            "Houdini API credentials are required. Set HOUDINI_API_KEY and HOUDINI_API_SECRET.",
        )

    user_ip = settings.houdini_user_ip.strip()
    if not user_ip:
        raise ProviderError(
            "houdini",
            "Houdini requires x-user-ip for compliance. Set HOUDINI_USER_IP first.",
        )

    user_agent = settings.houdini_user_agent.strip() or "AgentLayer/0.1.12"
    user_timezone = settings.houdini_user_timezone.strip() or "UTC"
    return {
        "Accept": "application/json",
        "Authorization": f"{api_key}:{api_secret}",
        "x-user-ip": user_ip,
        "x-user-agent": user_agent,
        "x-user-timezone": user_timezone,
    }


def _normalize_decimal_text(amount: Decimal) -> str:
    text = format(amount, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _to_decimal(value: Any, *, field_name: str) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ProviderError("houdini", f"{field_name} must be a valid decimal amount.") from exc
    if amount <= 0:
        raise ProviderError("houdini", f"{field_name} must be greater than zero.")
    return amount


def _normalize_token_record(token: dict[str, Any]) -> dict[str, Any]:
    min_max = token.get("minMax") if isinstance(token.get("minMax"), dict) else {}
    private_limits = min_max.get("private") if isinstance(min_max.get("private"), dict) else {}
    return {
        "id": str(token.get("id") or "").strip(),
        "symbol": str(token.get("symbol") or "").strip(),
        "name": str(token.get("name") or "").strip(),
        "address": str(token.get("address") or "").strip(),
        "chain": str(token.get("chain") or "").strip().lower(),
        "decimals": token.get("decimals"),
        "enabled": bool(token.get("enabled", True)),
        "has_cex": bool(token.get("hasCex", False)),
        "price": token.get("price"),
        "min_max_private": private_limits,
        "raw": token,
    }


def _unwrap_gateway_payload(
    status_code: int,
    payload: Any,
    *,
    operation: str,
) -> Any:
    if isinstance(payload, dict) and payload.get("ok") is False:
        message = str(payload.get("error") or f"{operation} failed.")
        raise ProviderError(
            "houdini-gateway",
            f"{operation} failed via provider gateway: {message}",
            details=payload,
        )

    if status_code != 200:
        message = payload
        if isinstance(payload, dict):
            message = payload.get("error") or payload
        raise ProviderError(
            "houdini-gateway",
            f"{operation} failed via provider gateway: {message}",
            details=payload if isinstance(payload, dict) else None,
        )

    return payload


async def _gateway_get(
    path: str,
    *,
    params: dict[str, Any] | None,
    operation: str,
) -> Any:
    client = get_client()
    response = await client.get(
        f"{_gateway_base_url()}{path}",
        params=params,
        headers=_gateway_headers(),
    )
    payload = _parse_json_response(response, provider="houdini-gateway", operation=operation)
    if _gateway_route_missing(response.status_code, payload) and _direct_houdini_enabled():
        return None
    return _unwrap_gateway_payload(
        response.status_code,
        payload,
        operation=operation,
    )


async def _gateway_post(
    path: str,
    *,
    body: dict[str, Any],
    operation: str,
) -> Any:
    client = get_client()
    response = await client.post(
        f"{_gateway_base_url()}{path}",
        json=body,
        headers={**_gateway_headers(), "Content-Type": "application/json"},
    )
    payload = _parse_json_response(response, provider="houdini-gateway", operation=operation)
    if _gateway_route_missing(response.status_code, payload) and _direct_houdini_enabled():
        return None
    return _unwrap_gateway_payload(
        response.status_code,
        payload,
        operation=operation,
    )


async def fetch_cex_tokens(*, chain: str) -> list[dict[str, Any]]:
    normalized_chain = str(chain or "").strip().lower()
    if not normalized_chain:
        raise ProviderError("houdini", "chain is required when fetching Houdini tokens.")

    cached = _CEX_TOKEN_CACHE.get(normalized_chain)
    now = time.time()
    if cached and now - cached[0] < _TOKEN_CACHE_TTL_SECONDS:
        return cached[1]

    tokens = await _fetch_cex_tokens_uncached(normalized_chain)

    _CEX_TOKEN_CACHE[normalized_chain] = (now, tokens)
    return tokens


async def _fetch_cex_tokens_uncached(chain: str) -> list[dict[str, Any]]:
    page = 1
    tokens: list[dict[str, Any]] = []
    client = get_client()
    while True:
        gateway_payload = None
        if _gateway_enabled():
            gateway_payload = await _gateway_get(
                "/v1/houdini/tokens",
                params={
                    "hasCex": "true",
                    "chain": chain,
                    "pageSize": 100,
                    "page": page,
                },
                operation="Houdini tokens",
            )
        if gateway_payload is not None:
            payload = gateway_payload
        else:
            response = await client.get(
                f"{_base_url()}/tokens",
                params={
                    "hasCex": "true",
                    "chain": chain,
                    "pageSize": 100,
                    "page": page,
                },
                headers=_require_compliance_headers(),
            )
            payload = _parse_json_response(response, provider="houdini", operation="Houdini tokens")
            if response.status_code != 200:
                raise ProviderError("houdini", f"HTTP {response.status_code}: {_normalize_error(payload)}")
        page_tokens = payload.get("tokens")
        if not isinstance(page_tokens, list):
            raise ProviderError("houdini", "Unexpected tokens response from Houdini.")
        tokens.extend(
            _normalize_token_record(item)
            for item in page_tokens
            if isinstance(item, dict) and item.get("enabled", True)
        )
        total_pages = int(payload.get("totalPages") or 1)
        if page >= total_pages:
            break
        page += 1
    return tokens


def _token_match_rank(term: str, token: dict[str, Any]) -> tuple[int, int, str]:
    lowered = term.strip().lower()
    symbol = str(token.get("symbol") or "").strip().lower()
    name = str(token.get("name") or "").strip().lower()
    address = str(token.get("address") or "").strip().lower()
    token_id = str(token.get("id") or "").strip().lower()

    if lowered == token_id:
        return (0, 0, symbol)
    if lowered == address:
        return (1, 0, symbol)
    if lowered == symbol:
        return (2, 0, symbol)
    if lowered == name:
        return (3, 0, symbol)
    if lowered in name or lowered in symbol or lowered in address:
        return (4, len(name), symbol)
    return (9, len(name), symbol)


async def resolve_cex_token(*, term: str, chain: str) -> dict[str, Any]:
    normalized_term = str(term or "").strip()
    if not normalized_term:
        raise ProviderError("houdini", "token term is required.")

    tokens = await fetch_cex_tokens(chain=chain)
    candidates = [
        token
        for token in tokens
        if token.get("enabled", True) and token.get("has_cex", True)
    ]
    ranked = sorted(
        enumerate(candidates),
        key=lambda pair: (_token_match_rank(normalized_term, pair[1]), pair[0]),
    )
    if not ranked or ranked[0][1] is None:
        raise ProviderError(
            "houdini",
            f"Houdini does not expose a CEX token match for '{normalized_term}' on {chain}.",
        )
    best_rank = _token_match_rank(normalized_term, ranked[0][1])
    if best_rank[0] >= 9:
        raise ProviderError(
            "houdini",
            f"Houdini does not expose a CEX token match for '{normalized_term}' on {chain}.",
        )
    resolved = ranked[0][1]
    if resolved.get("chain") != str(chain).strip().lower():
        raise ProviderError(
            "houdini",
            f"Houdini token '{normalized_term}' resolved to the wrong chain ({resolved.get('chain')}).",
        )
    return resolved


async def fetch_private_quotes(
    *,
    from_token_id: str,
    to_token_id: str,
    amount_ui: Decimal,
) -> list[dict[str, Any]]:
    payload = None
    if _gateway_enabled():
        payload = await _gateway_get(
            "/v1/houdini/quotes/private",
            params={
                "from": from_token_id,
                "to": to_token_id,
                "amount": _normalize_decimal_text(amount_ui),
            },
            operation="Houdini private quotes",
        )
    if payload is None:
        client = get_client()
        response = await client.get(
            f"{_base_url()}/quotes",
            params={
                "from": from_token_id,
                "to": to_token_id,
                "amount": _normalize_decimal_text(amount_ui),
                "types": "private",
            },
            headers=_require_compliance_headers(),
        )
        payload = _parse_json_response(response, provider="houdini", operation="Houdini private quotes")
        if response.status_code != 200:
            raise ProviderError("houdini", f"HTTP {response.status_code}: {_normalize_error(payload)}")
    quotes = payload.get("quotes")
    if not isinstance(quotes, list):
        raise ProviderError("houdini", "Unexpected quotes response from Houdini.")
    private_quotes = [
        item
        for item in quotes
        if isinstance(item, dict) and str(item.get("type") or "").strip().lower() == "private"
    ]
    if not private_quotes:
        raise ProviderError("houdini", "No private Houdini quote is available for this route.")
    return private_quotes


def select_best_private_quote(quotes: list[dict[str, Any]]) -> dict[str, Any]:
    if not quotes:
        raise ProviderError("houdini", "No private Houdini quote is available for this route.")

    def _sort_key(item: dict[str, Any]) -> tuple[Decimal, Decimal]:
        amount_out = _to_decimal(item.get("amountOut"), field_name="amountOut")
        try:
            duration = Decimal(str(item.get("duration") or 0))
        except (InvalidOperation, TypeError, ValueError):
            duration = Decimal("0")
        return (amount_out, Decimal("-1") * duration)

    return max(quotes, key=_sort_key)


async def create_multi_swap(
    *,
    orders: list[dict[str, Any]],
) -> dict[str, Any]:
    if not orders:
        raise ProviderError("houdini", "orders are required.")
    payload = None
    if _gateway_enabled():
        payload = await _gateway_post(
            "/v1/houdini/exchanges/multi",
            body={"orders": orders},
            operation="Houdini multi create",
        )
    if payload is None:
        client = get_client()
        response = await client.post(
            f"{_base_url()}/exchanges/multi",
            json={"orders": orders},
            headers={**_require_compliance_headers(), "Content-Type": "application/json"},
        )
        payload = _parse_json_response(response, provider="houdini", operation="Houdini multi create")
        if response.status_code != 200:
            raise ProviderError("houdini", f"HTTP {response.status_code}: {_normalize_error(payload)}")
    if not isinstance(payload, dict) or not isinstance(payload.get("orders"), list):
        raise ProviderError("houdini", "Unexpected multi-swap response from Houdini.")
    return payload


async def create_exchange(
    *,
    quote_id: str,
    destination_address: str,
) -> dict[str, Any]:
    normalized_quote_id = str(quote_id).strip()
    normalized_destination = str(destination_address).strip()
    if not normalized_quote_id:
        raise ProviderError("houdini", "quote_id is required.")
    if not normalized_destination:
        raise ProviderError("houdini", "destination_address is required.")

    body = {
        "quoteId": normalized_quote_id,
        "addressTo": normalized_destination,
    }
    payload = None
    if _gateway_enabled():
        payload = await _gateway_post(
            "/v1/houdini/exchanges",
            body=body,
            operation="Houdini exchange create",
        )
    if payload is None:
        client = get_client()
        response = await client.post(
            f"{_base_url()}/exchanges",
            json=body,
            headers={**_require_compliance_headers(), "Content-Type": "application/json"},
        )
        payload = _parse_json_response(response, provider="houdini", operation="Houdini exchange create")
        if response.status_code != 200:
            raise ProviderError("houdini", f"HTTP {response.status_code}: {_normalize_error(payload)}")
    if not isinstance(payload, dict) or not payload:
        raise ProviderError("houdini", "Unexpected exchange response from Houdini.")
    return payload


async def fetch_multi_status(*, multi_id: str) -> dict[str, Any]:
    payload = None
    normalized_multi_id = str(multi_id).strip()
    if _gateway_enabled():
        payload = await _gateway_get(
            f"/v1/houdini/exchanges/multi/{normalized_multi_id}",
            params=None,
            operation="Houdini multi status",
        )
    if payload is None:
        client = get_client()
        response = await client.get(
            f"{_base_url()}/exchanges/multi/{normalized_multi_id}",
            headers=_require_compliance_headers(),
        )
        payload = _parse_json_response(response, provider="houdini", operation="Houdini multi status")
        if response.status_code != 200:
            raise ProviderError("houdini", f"HTTP {response.status_code}: {_normalize_error(payload)}")
    if not isinstance(payload, dict) or not isinstance(payload.get("orders"), list):
        raise ProviderError("houdini", "Unexpected multi-status response from Houdini.")
    return payload


async def fetch_order_status(*, houdini_id: str) -> dict[str, Any]:
    payload = None
    normalized_houdini_id = str(houdini_id).strip()
    if not normalized_houdini_id:
        raise ProviderError("houdini", "houdini_id is required.")
    if _gateway_enabled():
        payload = await _gateway_get(
            f"/v1/houdini/orders/{normalized_houdini_id}",
            params=None,
            operation="Houdini order status",
        )
    if payload is None:
        client = get_client()
        response = await client.get(
            f"{_base_url()}/orders/{normalized_houdini_id}",
            headers=_require_compliance_headers(),
        )
        payload = _parse_json_response(response, provider="houdini", operation="Houdini order status")
        if response.status_code != 200:
            raise ProviderError("houdini", f"HTTP {response.status_code}: {_normalize_error(payload)}")
    if not isinstance(payload, dict) or not payload:
        raise ProviderError("houdini", "Unexpected order-status response from Houdini.")
    return payload


async def fetch_multi_solana_transactions(*, multi_id: str, sender: str) -> dict[str, Any]:
    payload = None
    normalized_multi_id = str(multi_id).strip()
    normalized_sender = str(sender).strip()
    if _gateway_enabled():
        payload = await _gateway_get(
            f"/v1/houdini/exchanges/multi/{normalized_multi_id}/tx",
            params={"sender": normalized_sender},
            operation="Houdini multi tx",
        )
    if payload is None:
        client = get_client()
        response = await client.get(
            f"{_base_url()}/exchanges/multi/{normalized_multi_id}/tx",
            params={"sender": normalized_sender},
            headers=_require_compliance_headers(),
        )
        payload = _parse_json_response(response, provider="houdini", operation="Houdini multi tx")
        if response.status_code != 200:
            raise ProviderError("houdini", f"HTTP {response.status_code}: {_normalize_error(payload)}")
    if not isinstance(payload, dict) or not isinstance(payload.get("transactions"), list):
        raise ProviderError("houdini", "Unexpected Solana batch transaction response from Houdini.")
    return payload

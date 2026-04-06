import json
import os
from typing import Any

import httpx
from dotenv import load_dotenv
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

load_dotenv()

APP_NAME = "provider-gateway"
APP_VERSION = "0.1.0"

ALLOWED_RPC_METHODS = {
    "getAccountInfo",
    "getBalance",
    "getBlockHeight",
    "getLatestBlockhash",
    "getMinimumBalanceForRentExemption",
    "getProgramAccounts",
    "getRecentPrioritizationFees",
    "getSignatureStatuses",
    "getSignaturesForAddress",
    "getStakeActivation",
    "getTokenAccountBalance",
    "getTokenAccountsByOwner",
    "getTokenSupply",
    "getTransaction",
    "getVersion",
    "getVoteAccounts",
    "getSlot",
    "simulateTransaction",
    "sendTransaction",
}

ALLOWED_EVM_RPC_METHODS = {
    "eth_blockNumber",
    "eth_call",
    "eth_chainId",
    "eth_estimateGas",
    "eth_feeHistory",
    "eth_gasPrice",
    "eth_getBalance",
    "eth_getBlockByNumber",
    "eth_getCode",
    "eth_getTransactionCount",
    "eth_getTransactionReceipt",
    "eth_maxPriorityFeePerGas",
    "eth_sendRawTransaction",
}


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _split_csv(name: str) -> list[str]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _trim(value: str | None) -> str:
    return (value or "").strip()


def _json_error(message: str, status_code: int = 400, extra: dict[str, Any] | None = None) -> JSONResponse:
    payload = {"ok": False, "error": message}
    if extra:
        payload.update(extra)
    return JSONResponse(payload, status_code=status_code)


def _require_bearer(request: Request) -> str | None:
    if not _bool_env("REQUIRE_BEARER_AUTH", False):
        return None

    expected = _trim(os.getenv("PROVIDER_GATEWAY_BEARER_TOKEN"))
    if not expected:
        raise RuntimeError(
            "REQUIRE_BEARER_AUTH=true but PROVIDER_GATEWAY_BEARER_TOKEN is not configured"
        )

    actual = request.headers.get("authorization", "")
    if actual != f"Bearer {expected}":
        return "Unauthorized"
    return None


def _require_machine_token(request: Request) -> str | None:
    if not _bool_env("REQUIRE_BEARER_AUTH", False):
        return None

    expected = _trim(os.getenv("PROVIDER_GATEWAY_BEARER_TOKEN"))
    if not expected:
        raise RuntimeError(
            "REQUIRE_BEARER_AUTH=true but PROVIDER_GATEWAY_BEARER_TOKEN is not configured"
        )

    actual = request.headers.get("authorization", "")
    if actual == f"Bearer {expected}":
        return None

    query_token = request.query_params.get("token", "").strip()
    if query_token == expected:
        return None

    return "Unauthorized"


def _http_timeout_seconds() -> float:
    raw = _trim(os.getenv("HTTP_TIMEOUT_SECONDS")) or "20"
    return max(float(raw), 1.0)


def _bags_base_url() -> str:
    return _trim(os.getenv("BAGS_API_BASE_URL")) or "https://public-api-v2.bags.fm/api/v1"


def _bags_headers() -> dict[str, str]:
    api_key = _trim(os.getenv("BAGS_API_KEY"))
    if not api_key:
        raise RuntimeError("BAGS_API_KEY is not configured")
    return {"x-api-key": api_key}


def _jupiter_lend_base_url() -> str:
    return _trim(os.getenv("JUPITER_LEND_API_BASE_URL")) or "https://api.jup.ag/lend/v1"


def _jupiter_headers() -> dict[str, str]:
    api_key = _trim(os.getenv("JUPITER_API_KEY"))
    if not api_key:
        raise RuntimeError("JUPITER_API_KEY is not configured")
    return {"x-api-key": api_key}


def _provider_url_from_env(name: str, default: str = "") -> str:
    return _trim(os.getenv(name)) or default


def _resolve_rpc_url(provider: str, network: str) -> tuple[str, str]:
    if network != "mainnet":
        raise RuntimeError("Shared provider gateway RPC is mainnet-only.")

    shared_url = _provider_url_from_env("SHARED_SOLANA_RPC_URL")
    helius_url = _provider_url_from_env("HELIUS_SHARED_RPC_URL")
    helius_key = _trim(os.getenv("HELIUS_API_KEY"))
    alchemy_url = _provider_url_from_env("ALCHEMY_SHARED_RPC_URL")
    alchemy_key = _trim(os.getenv("ALCHEMY_API_KEY"))

    if not helius_url and helius_key:
        helius_url = f"https://mainnet.helius-rpc.com/?api-key={helius_key}"
    if not alchemy_url and alchemy_key:
        alchemy_url = f"https://solana-mainnet.g.alchemy.com/v2/{alchemy_key}"

    if provider == "shared":
        if shared_url:
            return ("shared", shared_url)
        raise RuntimeError("SHARED_SOLANA_RPC_URL is not configured")

    if provider == "helius":
        if helius_url:
            return ("helius", helius_url)
        raise RuntimeError("Helius shared RPC is not configured")

    if provider == "alchemy":
        if alchemy_url:
            return ("alchemy", alchemy_url)
        raise RuntimeError("Alchemy shared RPC is not configured")

    if provider != "auto":
        raise RuntimeError(f"Unsupported RPC provider: {provider}")

    if shared_url:
        return ("shared", shared_url)
    if helius_url:
        return ("helius", helius_url)
    if alchemy_url:
        return ("alchemy", alchemy_url)
    raise RuntimeError(
        "No shared Solana RPC is configured. Set SHARED_SOLANA_RPC_URL, HELIUS_API_KEY/HELIUS_SHARED_RPC_URL, or ALCHEMY_API_KEY/ALCHEMY_SHARED_RPC_URL."
    )


def _resolve_evm_rpc_url(provider: str, network: str) -> tuple[str, str]:
    network_key = network.strip().lower()
    if network_key not in {"ethereum", "base"}:
        raise RuntimeError("Shared EVM provider gateway RPC currently supports only ethereum and base.")

    shared_by_network = {
        "ethereum": _provider_url_from_env("SHARED_EVM_ETHEREUM_RPC_URL"),
        "base": _provider_url_from_env("SHARED_EVM_BASE_RPC_URL"),
    }
    alchemy_url_by_network = {
        "ethereum": _provider_url_from_env("ALCHEMY_ETHEREUM_RPC_URL"),
        "base": _provider_url_from_env("ALCHEMY_BASE_RPC_URL"),
    }

    alchemy_key = _trim(os.getenv("ALCHEMY_API_KEY"))
    if alchemy_key:
        if not alchemy_url_by_network["ethereum"]:
            alchemy_url_by_network["ethereum"] = f"https://eth-mainnet.g.alchemy.com/v2/{alchemy_key}"
        if not alchemy_url_by_network["base"]:
            alchemy_url_by_network["base"] = f"https://base-mainnet.g.alchemy.com/v2/{alchemy_key}"

    if provider == "shared":
        shared_url = shared_by_network[network_key]
        if shared_url:
            return ("shared", shared_url)
        raise RuntimeError(f"Shared EVM RPC is not configured for {network_key}")

    if provider == "alchemy":
        alchemy_url = alchemy_url_by_network[network_key]
        if alchemy_url:
            return ("alchemy", alchemy_url)
        raise RuntimeError(f"Alchemy EVM RPC is not configured for {network_key}")

    if provider != "auto":
        raise RuntimeError(f"Unsupported EVM RPC provider: {provider}")

    if shared_by_network[network_key]:
        return ("shared", shared_by_network[network_key])
    if alchemy_url_by_network[network_key]:
        return ("alchemy", alchemy_url_by_network[network_key])
    raise RuntimeError(
        f"No shared EVM RPC is configured for {network_key}. "
        "Set SHARED_EVM_<NETWORK>_RPC_URL, ALCHEMY_<NETWORK>_RPC_URL, or ALCHEMY_API_KEY."
    )


def _status_payload() -> dict[str, Any]:
    configured_rpc = []
    for provider in ("shared", "helius", "alchemy"):
        try:
            resolved, _ = _resolve_rpc_url(provider, "mainnet")
            configured_rpc.append(resolved)
        except Exception:
            continue

    evm_rpc_upstreams: dict[str, list[str]] = {}
    for network in ("ethereum", "base"):
        available: list[str] = []
        for provider in ("shared", "alchemy"):
            try:
                resolved, _ = _resolve_evm_rpc_url(provider, network)
                available.append(resolved)
            except Exception:
                continue
        if available:
            evm_rpc_upstreams[network] = available

    return {
        "ok": True,
        "service": APP_NAME,
        "version": APP_VERSION,
        "auth_required": _bool_env("REQUIRE_BEARER_AUTH", False),
        "bags_configured": bool(_trim(os.getenv("BAGS_API_KEY"))),
        "rpc_upstreams": configured_rpc,
        "allowed_rpc_methods": sorted(ALLOWED_RPC_METHODS),
        "evm_rpc_upstreams": evm_rpc_upstreams,
        "allowed_evm_rpc_methods": sorted(ALLOWED_EVM_RPC_METHODS),
        "bags_features": {
            "trade_quote": True,
            "trade_swap": True,
            "claim_positions": True,
            "claim_transactions": True,
            "claim_analytics": True,
            "launch_token_info": True,
            "launch_fee_share_config": True,
            "launch_transaction": True,
        },
        "jupiter_earn_configured": bool(_trim(os.getenv("JUPITER_API_KEY"))),
        "jupiter_earn_features": {
            "earn_tokens": True,
            "earn_positions": True,
            "earn_earnings": True,
            "earn_deposit": True,
            "earn_withdraw": True,
        },
    }


def _require_query(request: Request, name: str) -> str:
    value = request.query_params.get(name, "").strip()
    if not value:
        raise ValueError(f"Missing required query parameter: {name}")
    return value


def _copy_optional_query(request: Request, names: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for name in names:
        value = request.query_params.get(name, "").strip()
        if value:
            result[name] = value
    return result


async def _http_get(url: str, *, headers: dict[str, str] | None = None, params: dict[str, Any] | None = None) -> tuple[int, Any]:
    async with httpx.AsyncClient(timeout=_http_timeout_seconds()) as client:
        response = await client.get(url, headers=headers, params=params)
    if not response.content:
        return response.status_code, {}
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, {"error": response.text[:500]}


async def _http_post(url: str, *, headers: dict[str, str] | None = None, json_body: dict[str, Any] | None = None) -> tuple[int, Any]:
    async with httpx.AsyncClient(timeout=_http_timeout_seconds()) as client:
        response = await client.post(url, headers=headers, json=json_body)
    if not response.content:
        return response.status_code, {}
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, {"error": response.text[:500]}


async def _http_post_form(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    data_body: dict[str, Any] | None = None,
    files: dict[str, tuple[str, bytes, str]] | None = None,
) -> tuple[int, Any]:
    async with httpx.AsyncClient(timeout=_http_timeout_seconds()) as client:
        response = await client.post(url, headers=headers, data=data_body, files=files)
    if not response.content:
        return response.status_code, {}
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, {"error": response.text[:500]}


def _require_body_dict(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ValueError("JSON body must be an object")
    return body


def _validate_evm_rpc_payload(body: Any) -> tuple[dict[str, Any] | list[dict[str, Any]], str]:
    if isinstance(body, dict):
        entries = [body]
        normalized_body: dict[str, Any] | list[dict[str, Any]] = body
    elif isinstance(body, list) and body:
        if any(not isinstance(item, dict) for item in body):
            raise ValueError("JSON-RPC batch body must contain only objects")
        entries = body
        normalized_body = body
    else:
        raise ValueError("JSON body must be an object or a non-empty array of objects")

    for entry in entries:
        method = str(entry.get("method", "")).strip()
        if not method:
            raise ValueError("Field 'method' is required")
        if method not in ALLOWED_EVM_RPC_METHODS:
            raise PermissionError(method)
        params = entry.get("params", [])
        if not isinstance(params, list):
            raise TypeError("Field 'params' must be an array")
        entry["jsonrpc"] = str(entry.get("jsonrpc", "2.0") or "2.0")
        if "id" not in entry:
            entry["id"] = 1

    return normalized_body, entries[0]["method"]


def _require_string_field(body: dict[str, Any], name: str) -> str:
    value = body.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Field '{name}' is required")
    return value.strip()


def _require_list_field(body: dict[str, Any], name: str) -> list[Any]:
    value = body.get(name)
    if not isinstance(value, list) or not value:
        raise ValueError(f"Field '{name}' is required and must be a non-empty array")
    return value


def _normalize_form_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, str)):
        return str(value)
    if isinstance(value, (list, dict)):
        return json.dumps(value, separators=(",", ":"))
    raise ValueError(f"Unsupported field type: {type(value).__name__}")


def _collect_form_fields_from_json(
    body: dict[str, Any],
    *,
    required_strings: list[str],
) -> dict[str, str]:
    data: dict[str, str] = {}
    for name in required_strings:
        value = body.get(name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Field '{name}' is required")
        data[name] = value.strip()

    for key, value in body.items():
        if key in data or value is None:
            continue
        data[key] = _normalize_form_scalar(value)
    return data


def _validate_fee_share_body(body: dict[str, Any]) -> None:
    _require_string_field(body, "payer")
    _require_string_field(body, "baseMint")
    claimers = _require_list_field(body, "claimersArray")
    basis_points = _require_list_field(body, "basisPointsArray")
    if len(claimers) != len(basis_points):
        raise ValueError("claimersArray and basisPointsArray must have the same length")
    if len(claimers) > 100:
        raise ValueError("Bags fee share supports at most 100 claimers")
    if any(not isinstance(item, str) or not item.strip() for item in claimers):
        raise ValueError("claimersArray must contain non-empty wallet strings")
    if any(not isinstance(item, int) or item < 0 for item in basis_points):
        raise ValueError("basisPointsArray must contain non-negative integers")
    if sum(basis_points) != 10_000:
        raise ValueError("basisPointsArray must sum to exactly 10000")


async def _parse_launch_token_info_request(
    request: Request,
) -> tuple[dict[str, str], dict[str, tuple[str, bytes, str]] | None]:
    content_type = request.headers.get("content-type", "").lower()
    if "multipart/form-data" in content_type:
        form = await request.form()
        data: dict[str, str] = {}
        files: dict[str, tuple[str, bytes, str]] = {}
        for key, value in form.multi_items():
            filename = getattr(value, "filename", None)
            if filename:
                if key not in {"image", "imageFile"}:
                    raise ValueError("Only 'image' upload field is supported")
                content = await value.read()
                files["image"] = (
                    filename or "upload.bin",
                    content,
                    value.content_type or "application/octet-stream",
                )
                continue
            data[key] = _normalize_form_scalar(value)
        for required in ("name", "symbol", "description"):
            if not data.get(required, "").strip():
                raise ValueError(f"Field '{required}' is required")
        return data, files or None

    try:
        body = _require_body_dict(await request.json())
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Invalid JSON body") from exc
    return _collect_form_fields_from_json(
        body,
        required_strings=["name", "symbol", "description"],
    ), None


async def health(_: Request) -> JSONResponse:
    return JSONResponse(_status_payload())


async def status(request: Request) -> JSONResponse:
    auth_error = _require_bearer(request)
    if auth_error:
        return _json_error(auth_error, 401)
    return JSONResponse(_status_payload())


async def rpc_proxy(request: Request) -> JSONResponse:
    auth_error = _require_bearer(request)
    if auth_error:
        return _json_error(auth_error, 401)

    try:
        body = await request.json()
    except Exception:
        return _json_error("Invalid JSON body", 400)

    if not isinstance(body, dict):
        return _json_error("JSON body must be an object", 400)

    method = str(body.get("method", "")).strip()
    if not method:
        return _json_error("Field 'method' is required", 400)
    if method not in ALLOWED_RPC_METHODS:
        return _json_error(
            f"RPC method '{method}' is not allowed",
            403,
            {"allowed_methods": sorted(ALLOWED_RPC_METHODS)},
        )

    params = body.get("params", [])
    if not isinstance(params, list):
        return _json_error("Field 'params' must be an array", 400)

    provider = str(body.get("provider", "auto")).strip().lower() or "auto"
    network = str(body.get("network", "mainnet")).strip().lower() or "mainnet"

    try:
        resolved_provider, rpc_url = _resolve_rpc_url(provider, network)
    except Exception as exc:
        return _json_error(str(exc), 403 if "mainnet-only" in str(exc) else 500)

    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}

    try:
        status_code, upstream = await _http_post(rpc_url, json_body=payload)
    except httpx.HTTPError as exc:
        return _json_error(f"RPC upstream error: {exc}", 502)

    return JSONResponse(
        {
            "ok": status_code < 500,
            "provider": resolved_provider,
            "upstream_status": status_code,
            "rpc": upstream,
        },
        status_code=200 if status_code < 500 else 502,
    )


async def evm_rpc_proxy(request: Request) -> JSONResponse:
    auth_error = _require_machine_token(request)
    if auth_error:
        return _json_error(auth_error, 401)

    try:
        body = await request.json()
    except Exception:
        return _json_error("Invalid JSON body", 400)

    try:
        payload, method = _validate_evm_rpc_payload(body)
    except ValueError as exc:
        return _json_error(str(exc), 400)
    except TypeError as exc:
        return _json_error(str(exc), 400)
    except PermissionError as exc:
        return _json_error(
            f"EVM RPC method '{str(exc)}' is not allowed",
            403,
            {"allowed_methods": sorted(ALLOWED_EVM_RPC_METHODS)},
        )

    provider = str(request.query_params.get("provider", "auto")).strip().lower() or "auto"
    network = str(request.path_params.get("network", "")).strip().lower()

    try:
        resolved_provider, rpc_url = _resolve_evm_rpc_url(provider, network)
    except Exception as exc:
        return _json_error(str(exc), 403 if "supports only" in str(exc) else 500)

    try:
        status_code, upstream = await _http_post(rpc_url, json_body=payload)
    except httpx.HTTPError as exc:
        return _json_error(f"EVM RPC upstream error: {exc}", 502)

    response = JSONResponse(upstream, status_code=200 if status_code < 500 else 502)
    response.headers["X-Provider-Gateway-Upstream"] = resolved_provider
    response.headers["X-Provider-Gateway-Network"] = network
    return response


async def bags_trade_quote(request: Request) -> JSONResponse:
    auth_error = _require_bearer(request)
    if auth_error:
        return _json_error(auth_error, 401)

    try:
        params = {
            "inputMint": _require_query(request, "inputMint"),
            "outputMint": _require_query(request, "outputMint"),
            "amount": _require_query(request, "amount"),
        }
        params.update(_copy_optional_query(request, ["slippageMode", "slippageBps"]))
    except ValueError as exc:
        return _json_error(str(exc), 400)

    try:
        status_code, payload = await _http_get(
            f"{_bags_base_url()}/trade/quote",
            headers=_bags_headers(),
            params=params,
        )
    except (RuntimeError, httpx.HTTPError) as exc:
        return _json_error(f"Bags quote error: {exc}", 502)

    return JSONResponse(payload, status_code=status_code)


async def bags_trade_swap(request: Request) -> JSONResponse:
    auth_error = _require_bearer(request)
    if auth_error:
        return _json_error(auth_error, 401)

    try:
        body = await request.json()
    except Exception:
        return _json_error("Invalid JSON body", 400)

    if not isinstance(body, dict):
        return _json_error("JSON body must be an object", 400)
    if not isinstance(body.get("quoteResponse"), dict):
        return _json_error("Field 'quoteResponse' is required and must be an object", 400)
    if not isinstance(body.get("userPublicKey"), str) or not body["userPublicKey"].strip():
        return _json_error("Field 'userPublicKey' is required", 400)

    try:
        status_code, payload = await _http_post(
            f"{_bags_base_url()}/trade/swap",
            headers={**_bags_headers(), "Content-Type": "application/json"},
            json_body=body,
        )
    except (RuntimeError, httpx.HTTPError) as exc:
        return _json_error(f"Bags swap error: {exc}", 502)

    return JSONResponse(payload, status_code=status_code)


async def bags_claim_positions(request: Request) -> JSONResponse:
    auth_error = _require_bearer(request)
    if auth_error:
        return _json_error(auth_error, 401)

    try:
        params = {"wallet": _require_query(request, "wallet")}
    except ValueError as exc:
        return _json_error(str(exc), 400)

    try:
        status_code, payload = await _http_get(
            f"{_bags_base_url()}/token-launch/claimable-positions",
            headers=_bags_headers(),
            params=params,
        )
    except (RuntimeError, httpx.HTTPError) as exc:
        return _json_error(f"Bags claim positions error: {exc}", 502)

    return JSONResponse(payload, status_code=status_code)


async def bags_claim_transactions(request: Request) -> JSONResponse:
    auth_error = _require_bearer(request)
    if auth_error:
        return _json_error(auth_error, 401)

    try:
        body = await request.json()
    except Exception:
        return _json_error("Invalid JSON body", 400)

    if not isinstance(body, dict):
        return _json_error("JSON body must be an object", 400)
    for required in ("feeClaimer", "tokenMint"):
        if not isinstance(body.get(required), str) or not body[required].strip():
            return _json_error(f"Field '{required}' is required", 400)

    try:
        status_code, payload = await _http_post(
            f"{_bags_base_url()}/token-launch/claim-txs/v3",
            headers={**_bags_headers(), "Content-Type": "application/json"},
            json_body=body,
        )
    except (RuntimeError, httpx.HTTPError) as exc:
        return _json_error(f"Bags claim tx error: {exc}", 502)

    return JSONResponse(payload, status_code=status_code)


async def bags_launch_token_info(request: Request) -> JSONResponse:
    auth_error = _require_bearer(request)
    if auth_error:
        return _json_error(auth_error, 401)

    try:
        data, files = await _parse_launch_token_info_request(request)
    except ValueError as exc:
        return _json_error(str(exc), 400)

    try:
        status_code, payload = await _http_post_form(
            f"{_bags_base_url()}/token-launch/create-token-info",
            headers=_bags_headers(),
            data_body=data,
            files=files,
        )
    except (RuntimeError, httpx.HTTPError) as exc:
        return _json_error(f"Bags launch token info error: {exc}", 502)

    return JSONResponse(payload, status_code=status_code)


async def bags_launch_fee_share_config(request: Request) -> JSONResponse:
    auth_error = _require_bearer(request)
    if auth_error:
        return _json_error(auth_error, 401)

    try:
        body = _require_body_dict(await request.json())
        _validate_fee_share_body(body)
    except ValueError as exc:
        return _json_error(str(exc), 400)
    except Exception:
        return _json_error("Invalid JSON body", 400)

    try:
        status_code, payload = await _http_post(
            f"{_bags_base_url()}/fee-share/config",
            headers={**_bags_headers(), "Content-Type": "application/json"},
            json_body=body,
        )
    except (RuntimeError, httpx.HTTPError) as exc:
        return _json_error(f"Bags fee share config error: {exc}", 502)

    return JSONResponse(payload, status_code=status_code)


async def bags_launch_transaction(request: Request) -> JSONResponse:
    auth_error = _require_bearer(request)
    if auth_error:
        return _json_error(auth_error, 401)

    try:
        body = _require_body_dict(await request.json())
        _require_string_field(body, "ipfs")
        _require_string_field(body, "tokenMint")
        _require_string_field(body, "wallet")
        _require_string_field(body, "configKey")
        if not str(body.get("initialBuyLamports", "")).strip():
            raise ValueError("Field 'initialBuyLamports' is required")
    except ValueError as exc:
        return _json_error(str(exc), 400)
    except Exception:
        return _json_error("Invalid JSON body", 400)

    try:
        status_code, payload = await _http_post(
            f"{_bags_base_url()}/token-launch/create-launch-transaction",
            headers={**_bags_headers(), "Content-Type": "application/json"},
            json_body=body,
        )
    except (RuntimeError, httpx.HTTPError) as exc:
        return _json_error(f"Bags launch transaction error: {exc}", 502)

    return JSONResponse(payload, status_code=status_code)


async def bags_fees_lifetime(request: Request) -> JSONResponse:
    auth_error = _require_bearer(request)
    if auth_error:
        return _json_error(auth_error, 401)

    try:
        params = {"tokenMint": _require_query(request, "tokenMint")}
    except ValueError as exc:
        return _json_error(str(exc), 400)

    try:
        status_code, payload = await _http_get(
            f"{_bags_base_url()}/token-launch/lifetime-fees",
            headers=_bags_headers(),
            params=params,
        )
    except (RuntimeError, httpx.HTTPError) as exc:
        return _json_error(f"Bags lifetime fees error: {exc}", 502)

    return JSONResponse(payload, status_code=status_code)


async def bags_fees_claim_stats(request: Request) -> JSONResponse:
    auth_error = _require_bearer(request)
    if auth_error:
        return _json_error(auth_error, 401)

    try:
        params = {"tokenMint": _require_query(request, "tokenMint")}
    except ValueError as exc:
        return _json_error(str(exc), 400)

    try:
        status_code, payload = await _http_get(
            f"{_bags_base_url()}/token-launch/claim-stats",
            headers=_bags_headers(),
            params=params,
        )
    except (RuntimeError, httpx.HTTPError) as exc:
        return _json_error(f"Bags claim stats error: {exc}", 502)

    return JSONResponse(payload, status_code=status_code)


async def bags_fees_claim_events(request: Request) -> JSONResponse:
    auth_error = _require_bearer(request)
    if auth_error:
        return _json_error(auth_error, 401)

    try:
        params = {"tokenMint": _require_query(request, "tokenMint")}
        params.update(_copy_optional_query(request, ["mode", "limit", "offset", "from", "to"]))
    except ValueError as exc:
        return _json_error(str(exc), 400)

    try:
        status_code, payload = await _http_get(
            f"{_bags_base_url()}/fee-share/token/claim-events",
            headers=_bags_headers(),
            params=params,
        )
    except (RuntimeError, httpx.HTTPError) as exc:
        return _json_error(f"Bags claim events error: {exc}", 502)

    return JSONResponse(payload, status_code=status_code)


def _split_csv_query(value: str) -> list[str]:
    items = [item.strip() for item in value.split(",") if item.strip()]
    if not items:
        raise ValueError("Query parameter must contain at least one value")
    return items


async def jupiter_earn_tokens(request: Request) -> JSONResponse:
    auth_error = _require_bearer(request)
    if auth_error:
        return _json_error(auth_error, 401)

    try:
        status_code, payload = await _http_get(
            f"{_jupiter_lend_base_url()}/earn/tokens",
            headers=_jupiter_headers(),
        )
    except (RuntimeError, httpx.HTTPError) as exc:
        return _json_error(f"Jupiter Earn tokens error: {exc}", 502)

    return JSONResponse(payload, status_code=status_code)


async def jupiter_earn_positions(request: Request) -> JSONResponse:
    auth_error = _require_bearer(request)
    if auth_error:
        return _json_error(auth_error, 401)

    try:
        users_raw = _require_query(request, "users")
        params = {"users": ",".join(_split_csv_query(users_raw))}
    except ValueError as exc:
        return _json_error(str(exc), 400)

    try:
        status_code, payload = await _http_get(
            f"{_jupiter_lend_base_url()}/earn/positions",
            headers=_jupiter_headers(),
            params=params,
        )
    except (RuntimeError, httpx.HTTPError) as exc:
        return _json_error(f"Jupiter Earn positions error: {exc}", 502)

    return JSONResponse(payload, status_code=status_code)


async def jupiter_earn_earnings(request: Request) -> JSONResponse:
    auth_error = _require_bearer(request)
    if auth_error:
        return _json_error(auth_error, 401)

    try:
        user = _require_query(request, "user")
        positions_raw = _require_query(request, "positions")
        params = {
            "user": user,
            "positions": ",".join(_split_csv_query(positions_raw)),
        }
    except ValueError as exc:
        return _json_error(str(exc), 400)

    try:
        status_code, payload = await _http_get(
            f"{_jupiter_lend_base_url()}/earn/earnings",
            headers=_jupiter_headers(),
            params=params,
        )
    except (RuntimeError, httpx.HTTPError) as exc:
        return _json_error(f"Jupiter Earn earnings error: {exc}", 502)

    return JSONResponse(payload, status_code=status_code)


async def jupiter_earn_deposit(request: Request) -> JSONResponse:
    auth_error = _require_bearer(request)
    if auth_error:
        return _json_error(auth_error, 401)

    try:
        body = _require_body_dict(await request.json())
        _require_string_field(body, "asset")
        _require_string_field(body, "signer")
        _require_string_field(body, "amount")
    except ValueError as exc:
        return _json_error(str(exc), 400)
    except Exception:
        return _json_error("Invalid JSON body", 400)

    try:
        status_code, payload = await _http_post(
            f"{_jupiter_lend_base_url()}/earn/deposit",
            headers={**_jupiter_headers(), "Content-Type": "application/json"},
            json_body=body,
        )
    except (RuntimeError, httpx.HTTPError) as exc:
        return _json_error(f"Jupiter Earn deposit error: {exc}", 502)

    return JSONResponse(payload, status_code=status_code)


async def jupiter_earn_withdraw(request: Request) -> JSONResponse:
    auth_error = _require_bearer(request)
    if auth_error:
        return _json_error(auth_error, 401)

    try:
        body = _require_body_dict(await request.json())
        _require_string_field(body, "asset")
        _require_string_field(body, "signer")
        _require_string_field(body, "amount")
    except ValueError as exc:
        return _json_error(str(exc), 400)
    except Exception:
        return _json_error("Invalid JSON body", 400)

    try:
        status_code, payload = await _http_post(
            f"{_jupiter_lend_base_url()}/earn/withdraw",
            headers={**_jupiter_headers(), "Content-Type": "application/json"},
            json_body=body,
        )
    except (RuntimeError, httpx.HTTPError) as exc:
        return _json_error(f"Jupiter Earn withdraw error: {exc}", 502)

    return JSONResponse(payload, status_code=status_code)


routes = [
    Route("/health", health, methods=["GET"]),
    Route("/v1/status", status, methods=["GET"]),
    Route("/v1/rpc", rpc_proxy, methods=["POST"]),
    Route("/v1/evm/rpc/{network:str}", evm_rpc_proxy, methods=["POST"]),
    Route("/v1/bags/trade/quote", bags_trade_quote, methods=["GET"]),
    Route("/v1/bags/trade/swap", bags_trade_swap, methods=["POST"]),
    Route("/v1/bags/launch/token-info", bags_launch_token_info, methods=["POST"]),
    Route("/v1/bags/launch/fee-share-config", bags_launch_fee_share_config, methods=["POST"]),
    Route("/v1/bags/launch/transaction", bags_launch_transaction, methods=["POST"]),
    Route("/v1/bags/claim/positions", bags_claim_positions, methods=["GET"]),
    Route("/v1/bags/claim/transactions", bags_claim_transactions, methods=["POST"]),
    Route("/v1/bags/fees/lifetime", bags_fees_lifetime, methods=["GET"]),
    Route("/v1/bags/fees/claim-stats", bags_fees_claim_stats, methods=["GET"]),
    Route("/v1/bags/fees/claim-events", bags_fees_claim_events, methods=["GET"]),
    Route("/v1/jupiter/earn/tokens", jupiter_earn_tokens, methods=["GET"]),
    Route("/v1/jupiter/earn/positions", jupiter_earn_positions, methods=["GET"]),
    Route("/v1/jupiter/earn/earnings", jupiter_earn_earnings, methods=["GET"]),
    Route("/v1/jupiter/earn/deposit", jupiter_earn_deposit, methods=["POST"]),
    Route("/v1/jupiter/earn/withdraw", jupiter_earn_withdraw, methods=["POST"]),
]

app = Starlette(debug=False, routes=routes)

allowed_origins = _split_csv("ALLOWED_ORIGINS")
if allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

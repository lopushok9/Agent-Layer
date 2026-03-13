"""Solana JSON-RPC provider with simple fallback logic."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from agent_wallet.exceptions import ProviderError
from agent_wallet.http_client import get_client

log = logging.getLogger(__name__)

SOLANA_RPC_FALLBACK = "https://api.mainnet-beta.solana.com"
LAMPORTS_PER_SOL = 1_000_000_000


def _fallback_for_rpc_url(rpc_url: str) -> str:
    """Choose a cluster-appropriate official fallback URL."""
    lowered = rpc_url.lower()
    if "devnet" in lowered:
        return "https://api.devnet.solana.com"
    if "testnet" in lowered:
        return "https://api.testnet.solana.com"
    return SOLANA_RPC_FALLBACK


def _normalize_rpc_urls(rpc_url: str | list[str]) -> list[str]:
    if isinstance(rpc_url, list):
        raw_values = rpc_url
    else:
        raw_values = [part.strip() for part in str(rpc_url).split(",")]

    candidates: list[str] = []
    for raw in raw_values:
        value = str(raw).strip()
        if value and value not in candidates:
            candidates.append(value)

    fallback = _fallback_for_rpc_url(candidates[0] if candidates else "")
    if fallback and fallback not in candidates:
        candidates.append(fallback)
    return candidates


def _retry_after_seconds(response: httpx.Response) -> float:
    header = response.headers.get("retry-after", "").strip()
    if not header:
        return 0.0
    try:
        return max(float(header), 0.0)
    except ValueError:
        return 0.0


async def _do_rpc_call(rpc_url: str, method: str, params: list[Any]) -> dict[str, Any]:
    client = get_client()
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    last_exc: Exception | None = None
    response: httpx.Response | None = None
    for attempt in range(3):
        try:
            response = await client.post(rpc_url, json=payload)
            if response.status_code == 429:
                wait_seconds = max(_retry_after_seconds(response), 0.5 * (attempt + 1))
                last_exc = ProviderError("solana-rpc", f"Rate limited on {rpc_url}")
                if attempt == 2:
                    raise last_exc
                await asyncio.sleep(wait_seconds)
                continue
            if response.status_code in {403, 500, 502, 503, 504}:
                last_exc = ProviderError("solana-rpc", f"HTTP {response.status_code} on {rpc_url}")
                if attempt == 2:
                    raise last_exc
                await asyncio.sleep(0.5 * (attempt + 1))
                continue
            break
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            last_exc = exc
            if attempt == 2:
                raise ProviderError("solana-rpc", f"Network error on {rpc_url}: {exc}") from exc
            await asyncio.sleep(0.5 * (attempt + 1))
    if response is None:
        raise ProviderError("solana-rpc", f"RPC request failed on {rpc_url}: {last_exc}")
    if response.status_code == 429:
        raise ProviderError("solana-rpc", f"Rate limited on {rpc_url}")
    if response.status_code != 200:
        raise ProviderError("solana-rpc", f"HTTP {response.status_code} on {rpc_url}")
    data = response.json()
    if "error" in data:
        raise ProviderError("solana-rpc", f"RPC error: {data['error']}")
    return data


async def rpc_call(
    method: str,
    params: list[Any],
    rpc_url: str | list[str],
) -> dict[str, Any]:
    """Execute a Solana RPC call with ordered failover across configured endpoints."""
    candidates = _normalize_rpc_urls(rpc_url)
    errors: list[str] = []
    for index, candidate in enumerate(candidates):
        try:
            return await _do_rpc_call(candidate, method, params)
        except Exception as exc:
            errors.append(f"{candidate}: {exc}")
            if index < len(candidates) - 1:
                log.warning("Solana RPC failed on %s: %s -- trying next endpoint", candidate, exc)
                continue
            raise ProviderError(
                "solana-rpc",
                "All Solana RPC endpoints failed: " + " | ".join(errors),
            ) from exc
    raise ProviderError("solana-rpc", "No Solana RPC endpoints are configured.")


async def fetch_balance(
    address: str,
    rpc_url: str,
    commitment: str = "confirmed",
) -> dict[str, Any]:
    """Fetch native SOL balance for a wallet."""
    data = await rpc_call(
        "getBalance",
        [address, {"commitment": commitment}],
        rpc_url=rpc_url,
    )
    lamports = data.get("result", {}).get("value", 0)
    return {
        "address": address,
        "chain": "solana",
        "balance_native": lamports / LAMPORTS_PER_SOL,
        "balance_usd": None,
        "source": "solana-rpc",
    }


async def account_exists(address: str, rpc_url: str) -> bool:
    """Return whether an on-chain account exists."""
    data = await fetch_account_info(address, rpc_url=rpc_url)
    return data is not None


async def fetch_account_info(
    address: str,
    rpc_url: str,
    encoding: str = "jsonParsed",
) -> dict[str, Any] | None:
    """Fetch account info for any Solana account."""
    data = await rpc_call(
        "getAccountInfo",
        [address, {"encoding": encoding}],
        rpc_url=rpc_url,
    )
    return data.get("result", {}).get("value")


async def fetch_token_supply_info(mint: str, rpc_url: str) -> dict[str, Any]:
    """Fetch token supply metadata including decimals."""
    data = await rpc_call(
        "getTokenSupply",
        [mint],
        rpc_url=rpc_url,
    )
    value = data.get("result", {}).get("value", {})
    return {
        "mint": mint,
        "amount": value.get("amount"),
        "decimals": value.get("decimals"),
        "ui_amount": value.get("uiAmount"),
        "source": "solana-rpc",
    }


async def fetch_token_account_balance(address: str, rpc_url: str) -> dict[str, Any]:
    """Fetch SPL token balance for a token account."""
    data = await rpc_call(
        "getTokenAccountBalance",
        [address],
        rpc_url=rpc_url,
    )
    value = data.get("result", {}).get("value", {})
    return {
        "amount": value.get("amount"),
        "decimals": value.get("decimals"),
        "ui_amount": value.get("uiAmount"),
        "source": "solana-rpc",
    }


async def fetch_token_accounts_by_owner(
    owner: str,
    rpc_url: str,
    token_program_id: str = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
) -> list[dict[str, Any]]:
    """Fetch parsed SPL token accounts for a wallet owner."""
    data = await rpc_call(
        "getTokenAccountsByOwner",
        [
            owner,
            {"programId": token_program_id},
            {"encoding": "jsonParsed"},
        ],
        rpc_url=rpc_url,
    )
    return data.get("result", {}).get("value", []) or []


async def fetch_latest_blockhash(rpc_url: str, commitment: str = "confirmed") -> dict[str, Any]:
    """Fetch latest blockhash for transaction building."""
    data = await rpc_call(
        "getLatestBlockhash",
        [{"commitment": commitment}],
        rpc_url=rpc_url,
    )
    value = data.get("result", {}).get("value", {})
    return {
        "blockhash": value.get("blockhash"),
        "last_valid_block_height": value.get("lastValidBlockHeight"),
        "source": "solana-rpc",
    }


async def fetch_recent_prioritization_fees(
    rpc_url: str,
    writable_accounts: list[str] | None = None,
) -> dict[str, Any]:
    """Fetch prioritization fee samples for future tx construction."""
    params: list[Any] = [writable_accounts or []]
    data = await rpc_call("getRecentPrioritizationFees", params, rpc_url=rpc_url)
    fees = data.get("result", []) or []
    return {
        "samples": fees,
        "recommended_micro_lamports": max(
            (item.get("prioritizationFee", 0) for item in fees),
            default=0,
        ),
        "source": "solana-rpc",
    }


async def fetch_minimum_balance_for_rent_exemption(
    space: int,
    rpc_url: str,
    commitment: str = "confirmed",
) -> dict[str, Any]:
    """Fetch rent-exempt minimum lamports for an account size."""
    data = await rpc_call(
        "getMinimumBalanceForRentExemption",
        [space, {"commitment": commitment}],
        rpc_url=rpc_url,
    )
    value = int(data.get("result") or 0)
    return {
        "space": space,
        "lamports": value,
        "source": "solana-rpc",
    }


async def fetch_vote_accounts(
    rpc_url: str,
    commitment: str = "confirmed",
) -> dict[str, Any]:
    """Fetch current and delinquent vote accounts."""
    data = await rpc_call(
        "getVoteAccounts",
        [{"commitment": commitment}],
        rpc_url=rpc_url,
    )
    value = data.get("result", {}) or {}
    return {
        "current": value.get("current", []) or [],
        "delinquent": value.get("delinquent", []) or [],
        "source": "solana-rpc",
    }


async def fetch_stake_activation(
    stake_account: str,
    rpc_url: str,
    commitment: str = "confirmed",
) -> dict[str, Any]:
    """Fetch activation status for a stake account."""
    try:
        data = await rpc_call(
            "getStakeActivation",
            [stake_account, {"commitment": commitment}],
            rpc_url=rpc_url,
        )
    except ProviderError as exc:
        if "Method not found" in str(exc):
            return {
                "state": "unknown",
                "active": None,
                "inactive": None,
                "source": "solana-rpc",
            }
        raise
    value = data.get("result", {}) or {}
    return {
        "state": value.get("state"),
        "active": value.get("active"),
        "inactive": value.get("inactive"),
        "source": "solana-rpc",
    }


async def send_transaction(
    transaction_base64: str,
    rpc_url: str,
    skip_preflight: bool = False,
    max_retries: int | None = None,
) -> dict[str, Any]:
    """Send a pre-signed transaction encoded as base64."""
    config: dict[str, Any] = {
        "encoding": "base64",
        "skipPreflight": skip_preflight,
        "preflightCommitment": "confirmed",
    }
    if max_retries is not None:
        config["maxRetries"] = max_retries

    data = await rpc_call(
        "sendTransaction",
        [transaction_base64, config],
        rpc_url=rpc_url,
    )
    return {"signature": data.get("result"), "source": "solana-rpc"}


async def request_airdrop(
    address: str,
    lamports: int,
    rpc_url: str,
    commitment: str = "confirmed",
) -> dict[str, Any]:
    """Request a devnet or testnet SOL airdrop."""
    data = await rpc_call(
        "requestAirdrop",
        [address, lamports, {"commitment": commitment}],
        rpc_url=rpc_url,
    )
    return {
        "signature": data.get("result"),
        "source": "solana-rpc",
    }


async def get_signature_status(
    signature: str,
    rpc_url: str,
    search_transaction_history: bool = True,
) -> dict[str, Any] | None:
    """Fetch signature status for a submitted transaction."""
    data = await rpc_call(
        "getSignatureStatuses",
        [[signature], {"searchTransactionHistory": search_transaction_history}],
        rpc_url=rpc_url,
    )
    values = data.get("result", {}).get("value", [])
    if not values:
        return None
    return values[0]


async def wait_for_confirmation(
    signature: str,
    rpc_url: str,
    timeout_seconds: float = 20.0,
    poll_interval_seconds: float = 1.0,
) -> dict[str, Any] | None:
    """Poll signature status until confirmed/finalized or timeout."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        status = await get_signature_status(signature, rpc_url=rpc_url)
        if status is not None:
            if status.get("err") is not None:
                raise ProviderError("solana-rpc", f"Transaction failed: {status['err']}")
            confirmation_status = status.get("confirmationStatus")
            if confirmation_status in {"confirmed", "finalized"}:
                return status
        await asyncio.sleep(poll_interval_seconds)
    return None

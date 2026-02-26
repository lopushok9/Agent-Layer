"""Wallet MCP tools backed by Turnkey (headless VPS friendly)."""

import json
import re

from cache import Cache
from config import settings
from providers import turnkey

WALLET_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{2,64}$")
ACCOUNT_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{2,64}$")
TURNKEY_ACCOUNT_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
HEX_RE = re.compile(r"^0x[0-9a-fA-F]+$")
ACTIVITY_ID_RE = re.compile(r"^[A-Za-z0-9-]{8,128}$")


def _validate_wallet_name(name: str) -> str:
    val = name.strip()
    if not WALLET_NAME_RE.match(val):
        raise ValueError(
            "Invalid wallet_name. Use 2-64 chars: letters, numbers, dot, underscore, dash."
        )
    return val


def _validate_account_name(name: str) -> str:
    val = name.strip()
    if not ACCOUNT_NAME_RE.match(val):
        raise ValueError(
            "Invalid account_name. Use 2-64 chars: letters, numbers, dot, underscore, dash."
        )
    return val


def _validate_turnkey_account(address: str) -> str:
    val = address.strip()
    if not TURNKEY_ACCOUNT_RE.match(val):
        raise ValueError("Invalid sign_with address. Expected EVM address (0x + 40 hex chars).")
    return val


def _validate_unsigned_tx(unsigned_transaction: str) -> str:
    val = unsigned_transaction.strip()
    if not HEX_RE.match(val):
        raise ValueError("Invalid unsigned_transaction. Expected 0x-prefixed hex string.")
    return val


def _validate_activity_id(activity_id: str) -> str:
    val = activity_id.strip()
    if not ACTIVITY_ID_RE.match(val):
        raise ValueError("Invalid activity_id format.")
    return val


def _validate_fingerprint(fingerprint: str) -> str:
    val = fingerprint.strip()
    if not val:
        raise ValueError("fingerprint cannot be empty.")
    return val


def register(mcp, cache: Cache):
    """Register Turnkey wallet tools."""

    @mcp.tool()
    async def turnkey_status() -> str:
        """Check Turnkey CLI/config readiness.

        Returns:
            JSON status with CLI presence and whether required settings are configured.
        """
        cache_key = "turnkey:status"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        status = await turnkey.get_status()
        result = json.dumps(status, ensure_ascii=False)
        cache.set(cache_key, result, 10)
        return result

    @mcp.tool()
    async def turnkey_create_wallet(wallet_name: str = "agent-wallet") -> str:
        """Create a new Turnkey wallet.

        Args:
            wallet_name: Logical wallet name in Turnkey (2-64 chars, [A-Za-z0-9._-]).
        """
        wallet_name = _validate_wallet_name(wallet_name)
        data = await turnkey.create_wallet(wallet_name)
        return json.dumps(data, ensure_ascii=False)

    @mcp.tool()
    async def turnkey_create_ethereum_account(
        wallet_name: str = "agent-wallet",
        account_name: str = "agent-main",
        derivation_path: str = "m/44'/60'/0'/0/0",
    ) -> str:
        """Create an Ethereum account in an existing Turnkey wallet.

        Args:
            wallet_name: Existing wallet name.
            account_name: New account label.
            derivation_path: BIP32 path (default m/44'/60'/0'/0/0).
        """
        wallet_name = _validate_wallet_name(wallet_name)
        account_name = _validate_account_name(account_name)
        data = await turnkey.create_wallet_account(
            wallet_name=wallet_name,
            account_name=account_name,
            path=derivation_path.strip(),
            address_format="ADDRESS_FORMAT_ETHEREUM",
        )
        return json.dumps(data, ensure_ascii=False)

    @mcp.tool()
    async def turnkey_list_accounts(wallet_name: str = "agent-wallet") -> str:
        """List accounts for a Turnkey wallet.

        Args:
            wallet_name: Existing wallet name.
        """
        wallet_name = _validate_wallet_name(wallet_name)
        data = await turnkey.list_wallet_accounts(wallet_name)
        return json.dumps(data, ensure_ascii=False)

    @mcp.tool()
    async def turnkey_sign_transaction(sign_with: str, unsigned_transaction: str) -> str:
        """Sign an unsigned Ethereum transaction with Turnkey account.

        Args:
            sign_with: Turnkey account address (0x...).
            unsigned_transaction: Unsigned transaction hex payload.
        """
        sign_with = _validate_turnkey_account(sign_with)
        unsigned_transaction = _validate_unsigned_tx(unsigned_transaction)
        data = await turnkey.sign_transaction(sign_with, unsigned_transaction)
        return json.dumps(data, ensure_ascii=False)

    @mcp.tool()
    async def turnkey_list_activities() -> str:
        """List organization activities (including pending consensus activities)."""
        data = await turnkey.list_activities()
        return json.dumps(data, ensure_ascii=False)

    @mcp.tool()
    async def turnkey_get_activity(activity_id: str) -> str:
        """Get details and status for one activity."""
        activity_id = _validate_activity_id(activity_id)
        data = await turnkey.get_activity(activity_id)
        return json.dumps(data, ensure_ascii=False)

    @mcp.tool()
    async def turnkey_approve_activity(
        activity_id: str = "",
        fingerprint: str = "",
    ) -> str:
        """Approve activity by activity_id or fingerprint."""
        activity_id = activity_id.strip()
        fingerprint = fingerprint.strip()
        if activity_id:
            activity_id = _validate_activity_id(activity_id)
        if fingerprint:
            fingerprint = _validate_fingerprint(fingerprint)
        data = await turnkey.approve_activity(activity_id=activity_id or None, fingerprint=fingerprint or None)
        return json.dumps(data, ensure_ascii=False)

    @mcp.tool()
    async def turnkey_reject_activity(
        activity_id: str = "",
        fingerprint: str = "",
    ) -> str:
        """Reject activity by activity_id or fingerprint."""
        activity_id = activity_id.strip()
        fingerprint = fingerprint.strip()
        if activity_id:
            activity_id = _validate_activity_id(activity_id)
        if fingerprint:
            fingerprint = _validate_fingerprint(fingerprint)
        data = await turnkey.reject_activity(activity_id=activity_id or None, fingerprint=fingerprint or None)
        return json.dumps(data, ensure_ascii=False)

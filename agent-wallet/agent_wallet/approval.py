"""Host-issued approval tokens for sensitive wallet actions."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from agent_wallet.config import resolve_approval_secret, settings
from agent_wallet.wallet_layer.base import WalletBackendError

APPROVAL_TOKEN_VERSION = 1


def _canonical_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _urlsafe_b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _urlsafe_b64_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _sign_payload(payload: dict[str, Any], secret: str) -> str:
    return _urlsafe_b64(
        hmac.new(secret.encode("utf-8"), _canonical_json(payload), hashlib.sha256).digest()
    )


def _approval_secret() -> str:
    secret = resolve_approval_secret().strip()
    if not secret:
        raise WalletBackendError(
            "AGENT_WALLET_APPROVAL_SECRET is required for execute mode. "
            "The host must issue approval tokens after explicit user confirmation."
        )
    return secret


def build_operation_binding(*, tool_name: str, network: str, summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "tool": tool_name,
        "network": str(network).strip().lower(),
        "summary": summary,
    }


def issue_approval_token(
    *,
    tool_name: str,
    network: str,
    summary: dict[str, Any],
    mainnet_confirmed: bool = False,
    ttl_seconds: int | None = None,
    issued_by: str = "host",
) -> str:
    secret = _approval_secret()
    now = int(time.time())
    ttl = ttl_seconds if ttl_seconds is not None else int(settings.agent_wallet_approval_ttl_seconds)
    if ttl <= 0:
        raise WalletBackendError("Approval token ttl must be greater than zero.")
    payload = {
        "v": APPROVAL_TOKEN_VERSION,
        "iat": now,
        "exp": now + ttl,
        "issued_by": issued_by,
        "binding": build_operation_binding(tool_name=tool_name, network=network, summary=summary),
        "mainnet_confirmed": bool(mainnet_confirmed),
    }
    signature = _sign_payload(payload, secret)
    return f"{_urlsafe_b64(_canonical_json(payload))}.{signature}"


def verify_approval_token(
    token: str,
    *,
    tool_name: str,
    network: str,
    summary: dict[str, Any],
    require_mainnet_confirmation: bool,
) -> dict[str, Any]:
    secret = _approval_secret()
    if not isinstance(token, str) or "." not in token:
        raise WalletBackendError("A valid approval_token is required for execute mode.")
    encoded_payload, encoded_sig = token.split(".", 1)
    try:
        payload = json.loads(_urlsafe_b64_decode(encoded_payload).decode("utf-8"))
    except Exception as exc:
        raise WalletBackendError("approval_token could not be parsed.") from exc
    if not isinstance(payload, dict) or int(payload.get("v") or 0) != APPROVAL_TOKEN_VERSION:
        raise WalletBackendError("approval_token version is invalid.")
    expected_sig = _sign_payload(payload, secret)
    if not hmac.compare_digest(encoded_sig, expected_sig):
        raise WalletBackendError("approval_token signature is invalid.")
    now = int(time.time())
    if int(payload.get("exp") or 0) < now:
        raise WalletBackendError("approval_token has expired.")

    expected_binding = build_operation_binding(tool_name=tool_name, network=network, summary=summary)
    if payload.get("binding") != expected_binding:
        raise WalletBackendError(
            "approval_token does not match the requested operation. Generate a new approval after previewing the exact action."
        )
    if require_mainnet_confirmation and payload.get("mainnet_confirmed") is not True:
        raise WalletBackendError("approval_token is missing explicit mainnet confirmation.")
    return payload

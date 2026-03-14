"""Local transaction verification helpers for provider-built Solana transactions."""

from __future__ import annotations

from typing import Any

from agent_wallet.wallet_layer.base import WalletBackendError

CORE_PROGRAM_IDS = {
    "11111111111111111111111111111111",  # system
    "ComputeBudget111111111111111111111111111111",
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
    "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
    "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL",
    "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr",
}


def _account_keys(message: Any) -> list[str]:
    keys = []
    for value in getattr(message, "account_keys", []) or []:
        keys.append(str(value))
    return keys


def _compiled_instructions(message: Any) -> list[Any]:
    return list(getattr(message, "instructions", []) or [])


def _header_required_signatures(message: Any) -> int:
    header = getattr(message, "header", None)
    return int(getattr(header, "num_required_signatures", 0) or 0)


def _program_ids(message: Any) -> list[str]:
    keys = _account_keys(message)
    values: list[str] = []
    for instruction in _compiled_instructions(message):
        index = int(getattr(instruction, "program_id_index", -1))
        if index < 0 or index >= len(keys):
            raise WalletBackendError("Provider transaction contains an invalid program id index.")
        values.append(keys[index])
    return values


def _assert_basic_wallet_binding(message: Any, *, wallet_address: str) -> list[str]:
    keys = _account_keys(message)
    if not keys:
        raise WalletBackendError("Provider transaction does not include account keys.")
    if keys[0] != wallet_address:
        raise WalletBackendError(
            "Provider transaction fee payer does not match the connected wallet address."
        )
    required_signatures = _header_required_signatures(message)
    if required_signatures != 1:
        raise WalletBackendError(
            "Provider transaction requires unexpected additional signers and was rejected."
        )
    if wallet_address not in keys:
        raise WalletBackendError("Provider transaction is not bound to the connected wallet.")
    return keys


def verify_provider_swap_transaction(
    message: Any,
    *,
    wallet_address: str,
    input_mint: str,
    output_mint: str,
) -> dict[str, Any]:
    keys = _assert_basic_wallet_binding(message, wallet_address=wallet_address)
    if input_mint not in keys:
        raise WalletBackendError(
            "Provider swap transaction does not reference the expected input mint."
        )
    if output_mint not in keys:
        raise WalletBackendError(
            "Provider swap transaction does not reference the expected output mint."
        )
    program_ids = _program_ids(message)
    if not program_ids:
        raise WalletBackendError("Provider swap transaction does not include any instructions.")
    return {
        "wallet_address": wallet_address,
        "program_ids": program_ids,
        "non_core_program_ids": [pid for pid in program_ids if pid not in CORE_PROGRAM_IDS],
        "account_key_count": len(keys),
        "instruction_count": len(_compiled_instructions(message)),
        "input_mint": input_mint,
        "output_mint": output_mint,
    }


def verify_provider_earn_transaction(
    message: Any,
    *,
    wallet_address: str,
    asset_mint: str,
) -> dict[str, Any]:
    keys = _assert_basic_wallet_binding(message, wallet_address=wallet_address)
    if asset_mint not in keys:
        raise WalletBackendError(
            "Provider Earn transaction does not reference the expected asset mint."
        )
    program_ids = _program_ids(message)
    if not program_ids:
        raise WalletBackendError("Provider Earn transaction does not include any instructions.")
    return {
        "wallet_address": wallet_address,
        "program_ids": program_ids,
        "non_core_program_ids": [pid for pid in program_ids if pid not in CORE_PROGRAM_IDS],
        "account_key_count": len(keys),
        "instruction_count": len(_compiled_instructions(message)),
        "asset_mint": asset_mint,
    }

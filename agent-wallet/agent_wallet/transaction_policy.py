"""Practical verification for provider-built Solana transactions before signing."""

from __future__ import annotations

from typing import Any

from agent_wallet.wallet_layer.base import WalletBackendError

SYSTEM_PROGRAM_ID = "11111111111111111111111111111111"
COMPUTE_BUDGET_PROGRAM_ID = "ComputeBudget111111111111111111111111111111"
TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM_ID = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
ATA_PROGRAM_ID = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
MEMO_PROGRAM_ID = "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"
JUPITER_V6_PROGRAM_ID = "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5Nt7NQYjN"
JUPITER_ULTRA_EXACT_OUT = "j1o2qRpjcyUwEvwtcfhEQefh773ZgjxcVRry7LDqg5X"
JUPITER_DCA_PROGRAM_ID = "DCA265Vj8a7wYymQG8LqM3m7A4QeV9hiC7VYh4S6Jsa"
JUPITER_EARN_PROGRAM_IDS = {
    "PerpKeKBQ8sJ6SLD9Q2D1M9M6A7E4vYDn8ApX2HFqRS",
    "JUP2jxvQY4Z6vV4rA8nWJq7T6Rk5P8L3bN4sH1mD9aR",
}

BASE_ALLOWED_PROGRAMS = {
    SYSTEM_PROGRAM_ID,
    COMPUTE_BUDGET_PROGRAM_ID,
    TOKEN_PROGRAM_ID,
    TOKEN_2022_PROGRAM_ID,
    ATA_PROGRAM_ID,
    MEMO_PROGRAM_ID,
}
SWAP_ALLOWED_PROGRAMS = BASE_ALLOWED_PROGRAMS | {
    JUPITER_V6_PROGRAM_ID,
    JUPITER_ULTRA_EXACT_OUT,
    JUPITER_DCA_PROGRAM_ID,
}
EARN_ALLOWED_PROGRAMS = BASE_ALLOWED_PROGRAMS | JUPITER_EARN_PROGRAM_IDS

FORBIDDEN_PROGRAMS = {
    "TokenSwap11111111111111111111111111111111",  # catch obvious swaps outside expected path
}


def _account_keys(message: Any) -> list[str]:
    return [str(value) for value in (getattr(message, "account_keys", []) or [])]


def _compiled_instructions(message: Any) -> list[Any]:
    return list(getattr(message, "instructions", []) or [])


def _header_required_signatures(message: Any) -> int:
    header = getattr(message, "header", None)
    return int(getattr(header, "num_required_signatures", 0) or 0)


def _program_id_for_instruction(message: Any, instruction: Any) -> str:
    keys = _account_keys(message)
    index = int(getattr(instruction, "program_id_index", -1))
    if index < 0 or index >= len(keys):
        raise WalletBackendError("Provider transaction contains an invalid program id index.")
    return keys[index]


def _program_ids(message: Any) -> list[str]:
    return [_program_id_for_instruction(message, ix) for ix in _compiled_instructions(message)]


def _assert_basic_wallet_binding(message: Any, *, wallet_address: str) -> list[str]:
    keys = _account_keys(message)
    if not keys:
        raise WalletBackendError("Provider transaction does not include account keys.")
    if keys[0] != wallet_address:
        raise WalletBackendError("Provider transaction fee payer does not match the connected wallet.")
    if wallet_address not in keys:
        raise WalletBackendError("Provider transaction is not bound to the connected wallet.")
    required_signatures = _header_required_signatures(message)
    if required_signatures != 1:
        raise WalletBackendError("Provider transaction requires unexpected additional signers.")
    return keys


def _assert_program_allowlist(program_ids: list[str], *, allowed_programs: set[str], label: str) -> None:
    if not program_ids:
        raise WalletBackendError(f"{label} transaction does not include any instructions.")
    forbidden = [pid for pid in program_ids if pid in FORBIDDEN_PROGRAMS]
    if forbidden:
        raise WalletBackendError(
            f"{label} transaction uses forbidden program ids: {', '.join(sorted(set(forbidden)))}"
        )
    unknown = [pid for pid in program_ids if pid not in allowed_programs]
    if unknown:
        raise WalletBackendError(
            f"{label} transaction uses unknown program ids: {', '.join(sorted(set(unknown)))}"
        )


def verify_provider_swap_transaction(
    message: Any,
    *,
    wallet_address: str,
    input_mint: str,
    output_mint: str,
) -> dict[str, Any]:
    keys = _assert_basic_wallet_binding(message, wallet_address=wallet_address)
    if input_mint not in keys:
        raise WalletBackendError("Provider swap transaction does not reference expected input mint.")
    if output_mint not in keys:
        raise WalletBackendError("Provider swap transaction does not reference expected output mint.")
    program_ids = _program_ids(message)
    _assert_program_allowlist(program_ids, allowed_programs=SWAP_ALLOWED_PROGRAMS, label="Swap")
    if not any(pid in {JUPITER_V6_PROGRAM_ID, JUPITER_ULTRA_EXACT_OUT, JUPITER_DCA_PROGRAM_ID} for pid in program_ids):
        raise WalletBackendError("Provider swap transaction is missing a recognized Jupiter swap program.")
    return {
        "wallet_address": wallet_address,
        "program_ids": program_ids,
        "account_key_count": len(keys),
        "instruction_count": len(_compiled_instructions(message)),
        "input_mint": input_mint,
        "output_mint": output_mint,
        "verified": True,
    }


def verify_provider_earn_transaction(
    message: Any,
    *,
    wallet_address: str,
    asset_mint: str,
) -> dict[str, Any]:
    keys = _assert_basic_wallet_binding(message, wallet_address=wallet_address)
    if asset_mint not in keys:
        raise WalletBackendError("Provider Earn transaction does not reference expected asset mint.")
    program_ids = _program_ids(message)
    _assert_program_allowlist(program_ids, allowed_programs=EARN_ALLOWED_PROGRAMS, label="Earn")
    if not any(pid in JUPITER_EARN_PROGRAM_IDS for pid in program_ids):
        raise WalletBackendError("Provider Earn transaction is missing a recognized Earn program.")
    return {
        "wallet_address": wallet_address,
        "program_ids": program_ids,
        "account_key_count": len(keys),
        "instruction_count": len(_compiled_instructions(message)),
        "asset_mint": asset_mint,
        "verified": True,
    }

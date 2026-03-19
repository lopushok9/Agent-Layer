"""Local transaction verification helpers for provider-built Solana transactions."""

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
JUPITER_ULTRA_EXACT_OUT_PROGRAM_ID = "j1o2qRpjcyUwEvwtcfhEQefh773ZgjxcVRry7LDqg5X"
JUPITER_DCA_PROGRAM_ID = "DCA265Vj8a7wYymQG8LqM3m7A4QeV9hiC7VYh4S6Jsa"

CORE_PROGRAM_IDS = {
    SYSTEM_PROGRAM_ID,
    COMPUTE_BUDGET_PROGRAM_ID,
    TOKEN_PROGRAM_ID,
    TOKEN_2022_PROGRAM_ID,
    ATA_PROGRAM_ID,
    MEMO_PROGRAM_ID,
}
SWAP_ALLOWED_PROGRAMS = CORE_PROGRAM_IDS | {
    JUPITER_V6_PROGRAM_ID,
    JUPITER_ULTRA_EXACT_OUT_PROGRAM_ID,
    JUPITER_DCA_PROGRAM_ID,
}
RECOGNIZED_JUPITER_SWAP_PROGRAMS = {
    JUPITER_V6_PROGRAM_ID,
    JUPITER_ULTRA_EXACT_OUT_PROGRAM_ID,
    JUPITER_DCA_PROGRAM_ID,
}
FORBIDDEN_PROGRAMS = {
    "TokenSwap11111111111111111111111111111111",
}


def _account_keys(message: Any) -> list[str]:
    return [str(value) for value in getattr(message, "account_keys", []) or []]


def _compiled_instructions(message: Any) -> list[Any]:
    return list(getattr(message, "instructions", []) or [])


def _header_required_signatures(message: Any) -> int:
    header = getattr(message, "header", None)
    return int(getattr(header, "num_required_signatures", 0) or 0)


def _required_signer_keys(message: Any) -> list[str]:
    keys = _account_keys(message)
    required = _header_required_signatures(message)
    if required <= 0:
        raise WalletBackendError("Provider transaction does not require any signers.")
    if required > len(keys):
        raise WalletBackendError("Provider transaction signer metadata is inconsistent.")
    return keys[:required]


def _program_ids(message: Any) -> list[str]:
    keys = _account_keys(message)
    values: list[str] = []
    for instruction in _compiled_instructions(message):
        index = int(getattr(instruction, "program_id_index", -1))
        if index < 0 or index >= len(keys):
            raise WalletBackendError("Provider transaction contains an invalid program id index.")
        values.append(keys[index])
    return values


def _assert_program_allowlist(
    program_ids: list[str],
    *,
    allowed_programs: set[str],
    label: str,
    reject_unknown: bool = True,
) -> list[str]:
    if not program_ids:
        raise WalletBackendError(f"{label} transaction does not include any instructions.")

    forbidden = [pid for pid in program_ids if pid in FORBIDDEN_PROGRAMS]
    if forbidden:
        raise WalletBackendError(
            f"{label} transaction uses forbidden program ids: {', '.join(sorted(set(forbidden)))}"
        )

    unknown = [pid for pid in program_ids if pid not in allowed_programs]
    if unknown and reject_unknown:
        raise WalletBackendError(
            f"{label} transaction uses unknown program ids: {', '.join(sorted(set(unknown)))}"
        )
    return sorted(set(unknown))


def _assert_basic_wallet_binding(message: Any, *, wallet_address: str) -> dict[str, Any]:
    keys = _account_keys(message)
    if not keys:
        raise WalletBackendError("Provider transaction does not include account keys.")
    signer_keys = _required_signer_keys(message)
    if wallet_address not in signer_keys:
        raise WalletBackendError(
            "Provider transaction does not require the connected wallet as an authorized signer."
        )
    if len(signer_keys) > 2:
        raise WalletBackendError(
            "Provider transaction requires unexpected additional signers and was rejected."
        )
    if wallet_address not in keys:
        raise WalletBackendError("Provider transaction is not bound to the connected wallet.")
    return {
        "account_keys": keys,
        "fee_payer": keys[0],
        "required_signer_keys": signer_keys,
        "required_signature_count": len(signer_keys),
        "wallet_signer_index": signer_keys.index(wallet_address),
        "sponsored_fee_payer": keys[0] != wallet_address,
    }


def verify_provider_swap_transaction(
    message: Any,
    *,
    wallet_address: str,
    input_mint: str,
    output_mint: str,
) -> dict[str, Any]:
    binding = _assert_basic_wallet_binding(message, wallet_address=wallet_address)
    keys = binding["account_keys"]
    if input_mint not in keys:
        raise WalletBackendError(
            "Provider swap transaction does not reference the expected input mint."
        )
    if output_mint not in keys:
        raise WalletBackendError(
            "Provider swap transaction does not reference the expected output mint."
        )
    program_ids = _program_ids(message)
    unknown_program_ids = _assert_program_allowlist(
        program_ids,
        allowed_programs=SWAP_ALLOWED_PROGRAMS,
        label="Swap",
        reject_unknown=False,
    )
    if not any(pid in RECOGNIZED_JUPITER_SWAP_PROGRAMS for pid in program_ids):
        raise WalletBackendError(
            "Provider swap transaction is missing a recognized Jupiter swap program."
        )
    return {
        "wallet_address": wallet_address,
        "fee_payer": binding["fee_payer"],
        "required_signer_keys": binding["required_signer_keys"],
        "required_signature_count": binding["required_signature_count"],
        "wallet_signer_index": binding["wallet_signer_index"],
        "sponsored_fee_payer": binding["sponsored_fee_payer"],
        "program_ids": program_ids,
        "unknown_program_ids": unknown_program_ids,
        "non_core_program_ids": [pid for pid in program_ids if pid not in CORE_PROGRAM_IDS],
        "account_key_count": len(keys),
        "instruction_count": len(_compiled_instructions(message)),
        "input_mint": input_mint,
        "output_mint": output_mint,
        "verified": True,
    }

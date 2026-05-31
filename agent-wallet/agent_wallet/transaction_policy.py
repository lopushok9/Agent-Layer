"""Local transaction verification helpers for provider-built Solana transactions."""

from __future__ import annotations

import struct
from typing import Any

from agent_wallet.wallet_layer.base import WalletBackendError

SYSTEM_PROGRAM_ID = "11111111111111111111111111111111"
COMPUTE_BUDGET_PROGRAM_ID = "ComputeBudget111111111111111111111111111111"
TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM_ID = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
ATA_PROGRAM_ID = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
MEMO_PROGRAM_ID = "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"
ADDRESS_LOOKUP_TABLE_PROGRAM_ID = "AddressLookupTab1e1111111111111111111111111"
JUPITER_V6_PROGRAM_ID = "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5Nt7NQYjN"
JUPITER_ULTRA_EXACT_OUT_PROGRAM_ID = "j1o2qRpjcyUwEvwtcfhEQefh773ZgjxcVRry7LDqg5X"
JUPITER_DCA_PROGRAM_ID = "DCA265Vj8a7wYymQG8LqM3m7A4QeV9hiC7VYh4S6Jsa"
KAMINO_LEND_PROGRAM_ID = "KLend2g3cP87fffoy8q1mQqGKjrxjC8boSyAYavgmjD"
NATIVE_SOL_MINT = "So11111111111111111111111111111111111111112"
DEFAULT_NATIVE_SOL_EXTRA_SPEND_ALLOWANCE_LAMPORTS = 10_000_000

CORE_PROGRAM_IDS = {
    SYSTEM_PROGRAM_ID,
    COMPUTE_BUDGET_PROGRAM_ID,
    TOKEN_PROGRAM_ID,
    TOKEN_2022_PROGRAM_ID,
    ATA_PROGRAM_ID,
    MEMO_PROGRAM_ID,
    ADDRESS_LOOKUP_TABLE_PROGRAM_ID,
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
KAMINO_ALLOWED_PROGRAMS = CORE_PROGRAM_IDS | {
    KAMINO_LEND_PROGRAM_ID,
}


def _static_account_keys(message: Any) -> list[str]:
    return [str(value) for value in getattr(message, "account_keys", []) or []]


def _account_keys(message: Any, loaded_addresses: list[str] | None = None) -> list[str]:
    keys = _static_account_keys(message)
    if loaded_addresses:
        keys.extend(str(value) for value in loaded_addresses)
    return keys


def _compiled_instructions(message: Any) -> list[Any]:
    return list(getattr(message, "instructions", []) or [])


def _header_required_signatures(message: Any) -> int:
    header = getattr(message, "header", None)
    return int(getattr(header, "num_required_signatures", 0) or 0)


def _required_signer_keys(message: Any) -> list[str]:
    keys = _static_account_keys(message)
    required = _header_required_signatures(message)
    if required <= 0:
        raise WalletBackendError("Provider transaction does not require any signers.")
    if required > len(keys):
        raise WalletBackendError("Provider transaction signer metadata is inconsistent.")
    return keys[:required]


def _program_ids(message: Any, loaded_addresses: list[str] | None = None) -> list[str]:
    keys = _account_keys(message, loaded_addresses)
    values: list[str] = []
    for instruction in _compiled_instructions(message):
        index = int(getattr(instruction, "program_id_index", -1))
        if index < 0 or index >= len(keys):
            raise WalletBackendError("Provider transaction contains an invalid program id index.")
        values.append(keys[index])
    return values


def _instruction_account_keys(
    message: Any,
    instruction: Any,
    *,
    loaded_addresses: list[str] | None = None,
) -> list[str]:
    keys = _account_keys(message, loaded_addresses)
    values: list[str] = []
    for raw_index in list(getattr(instruction, "accounts", []) or []):
        index = int(raw_index)
        if index < 0 or index >= len(keys):
            raise WalletBackendError("Provider transaction contains an invalid account index.")
        values.append(keys[index])
    return values


def _instruction_data_bytes(instruction: Any) -> bytes:
    raw = getattr(instruction, "data", b"")
    if isinstance(raw, bytes):
        return raw
    try:
        return bytes(raw)
    except Exception as exc:  # pragma: no cover - defensive bridge for solders internals
        raise WalletBackendError("Provider transaction instruction data could not be decoded.") from exc


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


def _assert_basic_wallet_binding(
    message: Any,
    *,
    wallet_address: str,
    loaded_addresses: list[str] | None = None,
) -> dict[str, Any]:
    keys = _account_keys(message, loaded_addresses)
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
    program_ids = _program_ids(message)

    # Native SOL routes can be represented via wrapped SOL / temporary accounts, and some
    # aggregator paths do not expose canonical mint addresses directly in account keys.
    # We therefore treat mint-key presence as advisory rather than a hard blocker. The
    # stronger swap-specific safety gate is the signed transaction simulation check below.
    input_mint_present = input_mint in keys
    output_mint_present = output_mint in keys

    unknown_program_ids = _assert_program_allowlist(
        program_ids,
        allowed_programs=SWAP_ALLOWED_PROGRAMS,
        label="Swap",
        reject_unknown=False,
    )
    recognized_jupiter_program_ids = [
        pid for pid in program_ids if pid in RECOGNIZED_JUPITER_SWAP_PROGRAMS
    ]
    return {
        "wallet_address": wallet_address,
        "fee_payer": binding["fee_payer"],
        "required_signer_keys": binding["required_signer_keys"],
        "required_signature_count": binding["required_signature_count"],
        "wallet_signer_index": binding["wallet_signer_index"],
        "sponsored_fee_payer": binding["sponsored_fee_payer"],
        "program_ids": program_ids,
        "unknown_program_ids": unknown_program_ids,
        "recognized_jupiter_program_ids": recognized_jupiter_program_ids,
        "has_recognized_jupiter_program": bool(recognized_jupiter_program_ids),
        "non_core_program_ids": [pid for pid in program_ids if pid not in CORE_PROGRAM_IDS],
        "account_key_count": len(keys),
        "instruction_count": len(_compiled_instructions(message)),
        "input_mint": input_mint,
        "output_mint": output_mint,
        "input_mint_present": input_mint_present,
        "output_mint_present": output_mint_present,
        "verified": True,
    }


def _coerce_token_balance_amount(balance: dict[str, Any]) -> int | None:
    ui_token_amount = balance.get("uiTokenAmount")
    if not isinstance(ui_token_amount, dict):
        return None
    amount = ui_token_amount.get("amount")
    try:
        return int(str(amount))
    except (TypeError, ValueError):
        return None


def _wallet_token_deltas_by_mint(
    simulation_value: dict[str, Any],
    *,
    wallet_address: str,
) -> dict[str, int]:
    deltas: dict[tuple[int, str], int] = {}
    for field, multiplier in (("preTokenBalances", -1), ("postTokenBalances", 1)):
        balances = simulation_value.get(field)
        if not isinstance(balances, list):
            continue
        for balance in balances:
            if not isinstance(balance, dict):
                continue
            owner = str(balance.get("owner") or "").strip()
            if owner != wallet_address:
                continue
            mint = str(balance.get("mint") or "").strip()
            if not mint:
                continue
            amount = _coerce_token_balance_amount(balance)
            if amount is None:
                continue
            try:
                account_index = int(balance.get("accountIndex"))
            except (TypeError, ValueError):
                account_index = -1
            key = (account_index, mint)
            deltas[key] = deltas.get(key, 0) + (amount * multiplier)

    by_mint: dict[str, int] = {}
    for (_, mint), delta in deltas.items():
        by_mint[mint] = by_mint.get(mint, 0) + delta
    return by_mint


def _native_lamport_delta(
    simulation_value: dict[str, Any],
    *,
    wallet_account_index: int | None,
) -> int | None:
    if wallet_account_index is None or wallet_account_index < 0:
        return None
    pre_balances = simulation_value.get("preBalances")
    post_balances = simulation_value.get("postBalances")
    if not isinstance(pre_balances, list) or not isinstance(post_balances, list):
        return None
    if wallet_account_index >= len(pre_balances) or wallet_account_index >= len(post_balances):
        return None
    try:
        return int(post_balances[wallet_account_index]) - int(pre_balances[wallet_account_index])
    except (TypeError, ValueError):
        return None


def verify_provider_swap_simulation_result(
    simulation_value: dict[str, Any],
    *,
    wallet_address: str,
    wallet_account_index: int | None,
    input_mint: str,
    output_mint: str,
    input_amount_raw: int,
    minimum_output_amount_raw: int,
    native_sol_extra_spend_allowance_lamports: int = (
        DEFAULT_NATIVE_SOL_EXTRA_SPEND_ALLOWANCE_LAMPORTS
    ),
) -> dict[str, Any]:
    """Validate simulated wallet balance effects for a provider-built swap.

    Static account keys are too brittle for Jupiter routes that use wrapped SOL,
    shared accounts, intermediate hops, or address lookup tables. Simulation is
    closer to the signing risk: what will this transaction do to this wallet?
    The checks below block only when RPC gives us concrete contradictory data.
    Missing balance metadata is returned as advisory warnings to preserve route
    reliability across provider/RPC response variants.
    """
    if not isinstance(simulation_value, dict):
        raise WalletBackendError(
            "Provider swap transaction simulation returned an unexpected payload.",
            code="transaction_simulation_invalid",
        )

    if simulation_value.get("err") is not None:
        raise WalletBackendError(
            "Provider swap transaction simulation failed.",
            code="transaction_simulation_failed",
            details={"simulation": simulation_value},
        )

    token_deltas = _wallet_token_deltas_by_mint(
        simulation_value,
        wallet_address=wallet_address,
    )
    native_delta = _native_lamport_delta(
        simulation_value,
        wallet_account_index=wallet_account_index,
    )
    warnings: list[str] = []
    enforced_checks: list[str] = ["simulation_err_is_none"]

    if input_mint == NATIVE_SOL_MINT:
        if native_delta is None:
            warnings.append("native_input_delta_unavailable")
        else:
            max_spend = max(input_amount_raw, 0) + max(
                native_sol_extra_spend_allowance_lamports,
                0,
            )
            if -native_delta > max_spend:
                raise WalletBackendError(
                    "Provider swap transaction simulation spends more native SOL than approved.",
                    code="swap_simulation_overspend",
                    details={
                        "input_mint": input_mint,
                        "approved_input_amount_raw": str(input_amount_raw),
                        "native_delta_lamports": str(native_delta),
                        "allowed_extra_lamports": str(
                            native_sol_extra_spend_allowance_lamports
                        ),
                    },
                )
            enforced_checks.append("native_input_spend_within_approved_amount")
    else:
        input_delta = token_deltas.get(input_mint)
        if input_delta is None:
            warnings.append("token_input_delta_unavailable")
        elif -input_delta > input_amount_raw:
            raise WalletBackendError(
                "Provider swap transaction simulation spends more input token than approved.",
                code="swap_simulation_overspend",
                details={
                    "input_mint": input_mint,
                    "approved_input_amount_raw": str(input_amount_raw),
                    "input_delta_raw": str(input_delta),
                },
            )
        else:
            enforced_checks.append("token_input_spend_within_approved_amount")

    if output_mint == NATIVE_SOL_MINT:
        if native_delta is None:
            warnings.append("native_output_delta_unavailable")
        else:
            warnings.append("native_output_delta_is_net_of_fees")
    else:
        output_delta = token_deltas.get(output_mint)
        if output_delta is None:
            warnings.append("token_output_delta_unavailable")
        elif output_delta < minimum_output_amount_raw:
            raise WalletBackendError(
                "Provider swap transaction simulation returns less output token than approved.",
                code="swap_simulation_min_output_not_met",
                details={
                    "output_mint": output_mint,
                    "minimum_output_amount_raw": str(minimum_output_amount_raw),
                    "output_delta_raw": str(output_delta),
                },
            )
        else:
            enforced_checks.append("token_output_meets_approved_minimum")

    return {
        "verified": True,
        "simulation_err": None,
        "wallet_address": wallet_address,
        "wallet_account_index": wallet_account_index,
        "input_mint": input_mint,
        "output_mint": output_mint,
        "input_amount_raw": str(input_amount_raw),
        "minimum_output_amount_raw": str(minimum_output_amount_raw),
        "token_deltas": {mint: str(delta) for mint, delta in sorted(token_deltas.items())},
        "native_delta_lamports": str(native_delta) if native_delta is not None else None,
        "enforced_checks": enforced_checks,
        "warnings": warnings,
    }


def verify_provider_bags_transaction(
    message: Any,
    *,
    wallet_address: str,
    token_mint: str,
    action: str,
    loaded_addresses: list[str] | None = None,
) -> dict[str, Any]:
    binding = _assert_basic_wallet_binding(
        message,
        wallet_address=wallet_address,
        loaded_addresses=loaded_addresses,
    )
    keys = binding["account_keys"]
    if token_mint not in keys:
        raise WalletBackendError(
            f"{action} transaction does not reference the expected token mint."
        )
    program_ids = _program_ids(message, loaded_addresses)
    unknown_program_ids = _assert_program_allowlist(
        program_ids,
        allowed_programs=CORE_PROGRAM_IDS,
        label=action,
        reject_unknown=False,
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
        "token_mint": token_mint,
        "action": action,
        "verified": True,
    }


def verify_provider_kamino_lend_transaction(
    message: Any,
    *,
    wallet_address: str,
    market_address: str,
    reserve_address: str,
    action: str,
    obligation_address: str | None = None,
    loaded_addresses: list[str] | None = None,
) -> dict[str, Any]:
    binding = _assert_basic_wallet_binding(
        message,
        wallet_address=wallet_address,
        loaded_addresses=loaded_addresses,
    )
    keys = binding["account_keys"]
    if market_address not in keys:
        raise WalletBackendError(
            f"{action} transaction does not reference the expected Kamino market."
        )
    if reserve_address not in keys:
        raise WalletBackendError(
            f"{action} transaction does not reference the expected Kamino reserve."
        )
    if obligation_address and obligation_address not in keys:
        raise WalletBackendError(
            f"{action} transaction does not reference the expected Kamino obligation."
        )
    program_ids = _program_ids(message, loaded_addresses)
    unknown_program_ids = _assert_program_allowlist(
        program_ids,
        allowed_programs=KAMINO_ALLOWED_PROGRAMS,
        label=action,
        reject_unknown=False,
    )
    recognized_kamino_program_ids = [
        pid for pid in program_ids if pid == KAMINO_LEND_PROGRAM_ID
    ]
    if not recognized_kamino_program_ids:
        raise WalletBackendError(
            f"{action} transaction does not include the expected Kamino lending program."
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
        "recognized_kamino_program_ids": recognized_kamino_program_ids,
        "has_recognized_kamino_program": True,
        "non_core_program_ids": [pid for pid in program_ids if pid not in CORE_PROGRAM_IDS],
        "account_key_count": len(keys),
        "instruction_count": len(_compiled_instructions(message)),
        "market_address": market_address,
        "reserve_address": reserve_address,
        "obligation_address": obligation_address,
        "action": action,
        "verified": True,
    }


def verify_provider_flash_transaction(
    message: Any,
    *,
    wallet_address: str,
    market_address: str,
    target_custody_address: str,
    collateral_custody_address: str,
    action: str,
    expected_program_ids: list[str],
    position_address: str | None = None,
    collateral_mint: str | None = None,
    loaded_addresses: list[str] | None = None,
) -> dict[str, Any]:
    binding = _assert_basic_wallet_binding(
        message,
        wallet_address=wallet_address,
        loaded_addresses=loaded_addresses,
    )
    keys = binding["account_keys"]
    if market_address not in keys:
        raise WalletBackendError(
            f"{action} transaction does not reference the expected Flash market account."
        )
    if target_custody_address not in keys:
        raise WalletBackendError(
            f"{action} transaction does not reference the expected Flash target custody."
        )
    if collateral_custody_address not in keys:
        raise WalletBackendError(
            f"{action} transaction does not reference the expected Flash collateral custody."
        )
    if position_address and position_address not in keys:
        raise WalletBackendError(
            f"{action} transaction does not reference the expected Flash position account."
        )
    if collateral_mint and collateral_mint not in keys:
        raise WalletBackendError(
            f"{action} transaction does not reference the expected Flash collateral mint."
        )

    allowed_programs = CORE_PROGRAM_IDS | {pid for pid in expected_program_ids if pid}
    program_ids = _program_ids(message, loaded_addresses)
    unknown_program_ids = _assert_program_allowlist(
        program_ids,
        allowed_programs=allowed_programs,
        label=action,
        reject_unknown=False,
    )
    recognized_flash_program_ids = [
        pid for pid in program_ids if pid in expected_program_ids
    ]
    if not recognized_flash_program_ids:
        raise WalletBackendError(
            f"{action} transaction does not include the expected Flash program."
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
        "recognized_flash_program_ids": recognized_flash_program_ids,
        "has_recognized_flash_program": True,
        "non_core_program_ids": [pid for pid in program_ids if pid not in CORE_PROGRAM_IDS],
        "account_key_count": len(keys),
        "instruction_count": len(_compiled_instructions(message)),
        "market_address": market_address,
        "target_custody_address": target_custody_address,
        "collateral_custody_address": collateral_custody_address,
        "position_address": position_address,
        "collateral_mint": collateral_mint,
        "action": action,
        "verified": True,
    }

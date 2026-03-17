"""Smoke tests for provider transaction verification policy."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.transaction_policy import (
    JUPITER_V6_PROGRAM_ID,
    SWAP_ALLOWED_PROGRAMS,
    verify_provider_swap_transaction,
)
from agent_wallet.wallet_layer.base import WalletBackendError


class _Header:
    def __init__(self, num_required_signatures: int):
        self.num_required_signatures = num_required_signatures


class _Instruction:
    def __init__(self, program_id_index: int):
        self.program_id_index = program_id_index


class _Message:
    def __init__(self, account_keys, instructions, num_required_signatures=1):
        self.account_keys = account_keys
        self.instructions = instructions
        self.header = _Header(num_required_signatures)


def main() -> None:
    wallet = "Wallet111111111111111111111111111111111111111"
    input_mint = "So11111111111111111111111111111111111111112"
    output_mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

    message = _Message(
        [wallet, input_mint, output_mint, JUPITER_V6_PROGRAM_ID],
        [_Instruction(3)],
    )
    result = verify_provider_swap_transaction(
        message,
        wallet_address=wallet,
        input_mint=input_mint,
        output_mint=output_mint,
    )
    assert result["verified"] is True
    assert JUPITER_V6_PROGRAM_ID in SWAP_ALLOWED_PROGRAMS

    bad_unknown = _Message(
        [wallet, input_mint, output_mint, "BadProgram1111111111111111111111111111111111"],
        [_Instruction(3)],
    )
    try:
        verify_provider_swap_transaction(
            bad_unknown,
            wallet_address=wallet,
            input_mint=input_mint,
            output_mint=output_mint,
        )
        raise AssertionError("expected verifier to reject unknown program")
    except WalletBackendError as exc:
        assert "unknown program ids" in str(exc)

    bad_no_jupiter = _Message(
        [wallet, input_mint, output_mint, "ComputeBudget111111111111111111111111111111"],
        [_Instruction(3)],
    )
    try:
        verify_provider_swap_transaction(
            bad_no_jupiter,
            wallet_address=wallet,
            input_mint=input_mint,
            output_mint=output_mint,
        )
        raise AssertionError("expected verifier to reject missing Jupiter program")
    except WalletBackendError as exc:
        assert "recognized Jupiter swap program" in str(exc)

    bad_signers = _Message(
        [wallet, input_mint, output_mint, JUPITER_V6_PROGRAM_ID],
        [_Instruction(3)],
        num_required_signatures=2,
    )
    try:
        verify_provider_swap_transaction(
            bad_signers,
            wallet_address=wallet,
            input_mint=input_mint,
            output_mint=output_mint,
        )
        raise AssertionError("expected verifier to reject extra signers")
    except WalletBackendError as exc:
        assert "unexpected additional signers" in str(exc)

    print("smoke_transaction_policy: ok")


if __name__ == "__main__":
    main()

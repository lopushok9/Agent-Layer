"""Smoke tests for provider transaction verification policy."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.transaction_policy import (
    KAMINO_LEND_PROGRAM_ID,
    JUPITER_V6_PROGRAM_ID,
    SWAP_ALLOWED_PROGRAMS,
    verify_provider_kamino_lend_transaction,
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
    sponsor = "Sponsor11111111111111111111111111111111111111"
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
    assert result["sponsored_fee_payer"] is False
    assert result["unknown_program_ids"] == []
    assert result["has_recognized_jupiter_program"] is True

    sponsored = _Message(
        [sponsor, wallet, input_mint, output_mint, JUPITER_V6_PROGRAM_ID],
        [_Instruction(4)],
        num_required_signatures=2,
    )
    sponsored_result = verify_provider_swap_transaction(
        sponsored,
        wallet_address=wallet,
        input_mint=input_mint,
        output_mint=output_mint,
    )
    assert sponsored_result["verified"] is True
    assert sponsored_result["sponsored_fee_payer"] is True
    assert sponsored_result["fee_payer"] == sponsor
    assert sponsored_result["wallet_signer_index"] == 1

    unknown_but_allowed = _Message(
        [wallet, input_mint, output_mint, JUPITER_V6_PROGRAM_ID, "BadProgram1111111111111111111111111111111111"],
        [_Instruction(3), _Instruction(4)],
    )
    unknown_result = verify_provider_swap_transaction(
        unknown_but_allowed,
        wallet_address=wallet,
        input_mint=input_mint,
        output_mint=output_mint,
    )
    assert unknown_result["verified"] is True
    assert unknown_result["unknown_program_ids"] == ["BadProgram1111111111111111111111111111111111"]
    assert unknown_result["has_recognized_jupiter_program"] is True

    no_recognized_jupiter = _Message(
        [wallet, input_mint, output_mint, "ComputeBudget111111111111111111111111111111"],
        [_Instruction(3)],
    )
    no_recognized_result = verify_provider_swap_transaction(
        no_recognized_jupiter,
        wallet_address=wallet,
        input_mint=input_mint,
        output_mint=output_mint,
    )
    assert no_recognized_result["verified"] is True
    assert no_recognized_result["has_recognized_jupiter_program"] is False
    assert no_recognized_result["recognized_jupiter_program_ids"] == []

    bad_wallet_not_signer = _Message(
        [sponsor, input_mint, output_mint, wallet, JUPITER_V6_PROGRAM_ID],
        [_Instruction(4)],
        num_required_signatures=1,
    )
    try:
        verify_provider_swap_transaction(
            bad_wallet_not_signer,
            wallet_address=wallet,
            input_mint=input_mint,
            output_mint=output_mint,
        )
        raise AssertionError("expected verifier to reject wallet-not-signer transaction")
    except WalletBackendError as exc:
        assert "authorized signer" in str(exc)

    bad_signers = _Message(
        [sponsor, wallet, "ExtraSigner1111111111111111111111111111111111", input_mint, output_mint, JUPITER_V6_PROGRAM_ID],
        [_Instruction(5)],
        num_required_signatures=3,
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

    kamino_market = "7u3HeHxYDLhnCoErrtycNokbQYbWGzLs6JSDqGAv5PfF"
    kamino_reserve = "D6q6wuQSrifJKZYpR1M8R4YawnLDtDsMmWM1NbBmgJ59"
    kamino_message = _Message(
        [wallet, kamino_market, kamino_reserve, KAMINO_LEND_PROGRAM_ID],
        [_Instruction(3)],
    )
    kamino_result = verify_provider_kamino_lend_transaction(
        kamino_message,
        wallet_address=wallet,
        market_address=kamino_market,
        reserve_address=kamino_reserve,
        action="Kamino deposit",
    )
    assert kamino_result["verified"] is True
    assert kamino_result["has_recognized_kamino_program"] is True
    assert kamino_result["unknown_program_ids"] == []

    kamino_lookup_message = _Message(
        [wallet, KAMINO_LEND_PROGRAM_ID],
        [_Instruction(1)],
    )
    kamino_lookup_result = verify_provider_kamino_lend_transaction(
        kamino_lookup_message,
        wallet_address=wallet,
        market_address=kamino_market,
        reserve_address=kamino_reserve,
        action="Kamino deposit",
        loaded_addresses=[kamino_market, kamino_reserve],
    )
    assert kamino_lookup_result["verified"] is True
    assert kamino_lookup_result["account_key_count"] == 4

    bad_kamino = _Message(
        [wallet, kamino_market, kamino_reserve, "BadProgram1111111111111111111111111111111111"],
        [_Instruction(3)],
    )
    try:
        verify_provider_kamino_lend_transaction(
            bad_kamino,
            wallet_address=wallet,
            market_address=kamino_market,
            reserve_address=kamino_reserve,
            action="Kamino deposit",
        )
        raise AssertionError("expected verifier to reject missing Kamino program")
    except WalletBackendError as exc:
        assert "Kamino lending program" in str(exc)

    print("smoke_transaction_policy: ok")


if __name__ == "__main__":
    main()

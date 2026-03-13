"""Helpers for native Solana stake program instructions."""

from __future__ import annotations

import struct

from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey


STAKE_PROGRAM_ID = Pubkey.from_string("Stake11111111111111111111111111111111111111")
STAKE_CONFIG_ID = Pubkey.from_string("StakeConfig11111111111111111111111111111111")
SYSVAR_CLOCK_ID = Pubkey.from_string("SysvarC1ock11111111111111111111111111111111")
SYSVAR_STAKE_HISTORY_ID = Pubkey.from_string("SysvarStakeHistory1111111111111111111111111")
SYSVAR_RENT_ID = Pubkey.from_string("SysvarRent111111111111111111111111111111111")
STAKE_STATE_V2_SIZE = 200

STAKE_INSTR_DELEGATE = 2
STAKE_INSTR_WITHDRAW = 4
STAKE_INSTR_DEACTIVATE = 5
STAKE_INSTR_INITIALIZE_CHECKED = 9


def _stake_variant(index: int) -> bytes:
    return struct.pack("<I", index)


def initialize_checked(
    *,
    stake_account: Pubkey,
    staker: Pubkey,
    withdrawer: Pubkey,
) -> Instruction:
    """Build InitializeChecked for a new stake account."""
    return Instruction(
        STAKE_PROGRAM_ID,
        _stake_variant(STAKE_INSTR_INITIALIZE_CHECKED),
        [
            AccountMeta(stake_account, is_signer=False, is_writable=True),
            AccountMeta(SYSVAR_RENT_ID, is_signer=False, is_writable=False),
            AccountMeta(staker, is_signer=False, is_writable=False),
            AccountMeta(withdrawer, is_signer=False, is_writable=False),
        ],
    )


def delegate_stake(
    *,
    stake_account: Pubkey,
    vote_account: Pubkey,
    authority: Pubkey,
) -> Instruction:
    """Build DelegateStake for an initialized stake account."""
    return Instruction(
        STAKE_PROGRAM_ID,
        _stake_variant(STAKE_INSTR_DELEGATE),
        [
            AccountMeta(stake_account, is_signer=False, is_writable=True),
            AccountMeta(vote_account, is_signer=False, is_writable=False),
            AccountMeta(SYSVAR_CLOCK_ID, is_signer=False, is_writable=False),
            AccountMeta(SYSVAR_STAKE_HISTORY_ID, is_signer=False, is_writable=False),
            AccountMeta(STAKE_CONFIG_ID, is_signer=False, is_writable=False),
            AccountMeta(authority, is_signer=True, is_writable=False),
        ],
    )


def deactivate_stake(
    *,
    stake_account: Pubkey,
    authority: Pubkey,
) -> Instruction:
    """Build Deactivate for a delegated stake account."""
    return Instruction(
        STAKE_PROGRAM_ID,
        _stake_variant(STAKE_INSTR_DEACTIVATE),
        [
            AccountMeta(stake_account, is_signer=False, is_writable=True),
            AccountMeta(SYSVAR_CLOCK_ID, is_signer=False, is_writable=False),
            AccountMeta(authority, is_signer=True, is_writable=False),
        ],
    )


def withdraw_stake(
    *,
    stake_account: Pubkey,
    recipient: Pubkey,
    authority: Pubkey,
    lamports: int,
) -> Instruction:
    """Build Withdraw for an inactive or partially withdrawable stake account."""
    return Instruction(
        STAKE_PROGRAM_ID,
        struct.pack("<IQ", STAKE_INSTR_WITHDRAW, lamports),
        [
            AccountMeta(stake_account, is_signer=False, is_writable=True),
            AccountMeta(recipient, is_signer=False, is_writable=True),
            AccountMeta(SYSVAR_CLOCK_ID, is_signer=False, is_writable=False),
            AccountMeta(SYSVAR_STAKE_HISTORY_ID, is_signer=False, is_writable=False),
            AccountMeta(authority, is_signer=True, is_writable=False),
        ],
    )

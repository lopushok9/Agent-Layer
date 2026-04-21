from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class ParsedIntent:
    intent: str
    amount: float | None = None
    payment_asset: str | None = None
    target_asset: str | None = None
    compare_asset: str | None = None
    needs_clarification: bool = False
    clarifying_question: str | None = None
    assistant_summary: str | None = None


@dataclass
class Preview:
    operation_type: str
    from_asset: str
    to_asset: str
    from_amount: float
    fee_amount: float
    net_input_amount: float
    to_amount: float
    price_from_rub: float
    price_to_rub: float
    summary: str
    balances_after: dict[str, float]


@dataclass
class PendingAction:
    id: int
    user_id: int
    action_type: str
    payload: dict[str, Any]
    expires_at: datetime


@dataclass
class TransactionRecord:
    type: str
    from_asset: str
    to_asset: str
    from_amount: float
    to_amount: float
    fee_amount: float
    created_at: str

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

from .constants import (
    ASSET_DISPLAY,
    ASSET_RISK_NOTES,
    DEMO_PRICES_RUB,
    FEE_RATE,
    SUPPORTED_ASSETS,
)
from .models import ParsedIntent, Preview, TransactionRecord


UTC = timezone.utc


def format_amount(value: float, asset: str) -> str:
    if asset in {"BTC"}:
        return f"{value:,.6f}".replace(",", " ")
    if asset in {"SOL", "TSLAX", "NVDAX"}:
        return f"{value:,.4f}".replace(",", " ")
    if asset in {"USDT", "A7A5"}:
        return f"{value:,.2f}".replace(",", " ")
    return f"{value:,.2f}".replace(",", " ")


def ensure_supported_asset(asset: str | None) -> str:
    if not asset or asset not in SUPPORTED_ASSETS:
        raise ValueError("Unsupported asset")
    return asset


def build_preview(intent: ParsedIntent, balances: dict[str, float]) -> Preview:
    operation_type = intent.intent
    from_asset = ensure_supported_asset(intent.payment_asset)
    to_asset = ensure_supported_asset(intent.target_asset)
    if from_asset == to_asset:
        raise ValueError("Source and target assets must differ")
    if intent.amount is None or intent.amount <= 0:
        raise ValueError("Amount must be positive")

    from_amount = float(intent.amount)
    current_balance = float(balances.get(from_asset, 0.0))
    if current_balance < from_amount:
        raise ValueError(
            f"Insufficient balance: available {format_amount(current_balance, from_asset)} {ASSET_DISPLAY[from_asset]}"
        )

    fee_amount = from_amount * FEE_RATE
    net_input_amount = from_amount - fee_amount
    if net_input_amount <= 0:
        raise ValueError("Net input amount must stay positive after fee")

    price_from_rub = DEMO_PRICES_RUB[from_asset]
    price_to_rub = DEMO_PRICES_RUB[to_asset]
    to_amount = net_input_amount * price_from_rub / price_to_rub

    balances_after = deepcopy(balances)
    balances_after[from_asset] = current_balance - from_amount
    balances_after[to_asset] = float(balances.get(to_asset, 0.0)) + to_amount

    verb = "демо-покупку" if operation_type == "buy_asset" else "демо-обмен"
    summary = (
        f"Подготовил {verb} {ASSET_DISPLAY[to_asset]} на {format_amount(from_amount, from_asset)} "
        f"{ASSET_DISPLAY[from_asset]}. По демо-курсу вы получите {format_amount(to_amount, to_asset)} "
        f"{ASSET_DISPLAY[to_asset]}. Комиссия 0.6% = {format_amount(fee_amount, from_asset)} "
        f"{ASSET_DISPLAY[from_asset]}. После операции у вас останется "
        f"{format_amount(balances_after[from_asset], from_asset)} {ASSET_DISPLAY[from_asset]}. "
        f"Это виртуальная сделка для демонстрации UX. Подтверждаете?"
    )

    return Preview(
        operation_type=operation_type,
        from_asset=from_asset,
        to_asset=to_asset,
        from_amount=from_amount,
        fee_amount=fee_amount,
        net_input_amount=net_input_amount,
        to_amount=to_amount,
        price_from_rub=price_from_rub,
        price_to_rub=price_to_rub,
        summary=summary,
        balances_after=balances_after,
    )


def preview_to_payload(preview: Preview) -> dict[str, float | str | dict[str, float]]:
    return {
        "operation_type": preview.operation_type,
        "from_asset": preview.from_asset,
        "to_asset": preview.to_asset,
        "from_amount": preview.from_amount,
        "fee_amount": preview.fee_amount,
        "net_input_amount": preview.net_input_amount,
        "to_amount": preview.to_amount,
        "price_from_rub": preview.price_from_rub,
        "price_to_rub": preview.price_to_rub,
        "summary": preview.summary,
        "balances_after": preview.balances_after,
    }


def payload_to_transaction(payload: dict[str, float | str | dict[str, float]]) -> TransactionRecord:
    return TransactionRecord(
        type=str(payload["operation_type"]),
        from_asset=str(payload["from_asset"]),
        to_asset=str(payload["to_asset"]),
        from_amount=float(payload["from_amount"]),
        to_amount=float(payload["to_amount"]),
        fee_amount=float(payload["fee_amount"]),
        created_at=datetime.now(tz=UTC).isoformat(),
    )


def portfolio_text(balances: dict[str, float]) -> str:
    total_rub = 0.0
    lines = ["Демо-портфель:"]
    for asset in SUPPORTED_ASSETS:
        amount = float(balances.get(asset, 0.0))
        rub_value = amount * DEMO_PRICES_RUB[asset]
        total_rub += rub_value
        if amount <= 0:
            continue
        lines.append(
            f"- {ASSET_DISPLAY[asset]}: {format_amount(amount, asset)} "
            f"(~ {format_amount(rub_value, 'RUB')} RUB)"
        )
    lines.append(f"- Итого: ~ {format_amount(total_rub, 'RUB')} RUB")
    return "\n".join(lines)


def balance_text(balances: dict[str, float]) -> str:
    rub = float(balances.get("RUB", 0.0))
    usdt = float(balances.get("USDT", 0.0))
    return (
        "Краткий демо-баланс:\n"
        f"- RUB: {format_amount(rub, 'RUB')}\n"
        f"- USDT: {format_amount(usdt, 'USDT')}"
    )


def history_text(rows: list) -> str:
    if not rows:
        return "История пока пустая."
    lines = ["Последние операции:"]
    for row in rows:
        lines.append(
            f"- {row['created_at'][:16]} | {row['type']} | "
            f"{format_amount(float(row['from_amount']), row['from_asset'])} {ASSET_DISPLAY[row['from_asset']]} "
            f"-> {format_amount(float(row['to_amount']), row['to_asset'])} {ASSET_DISPLAY[row['to_asset']]} "
            f"| fee {format_amount(float(row['fee_amount']), row['from_asset'])} {ASSET_DISPLAY[row['from_asset']]}"
        )
    return "\n".join(lines)


def compare_text(amount: float, payment_asset: str, first_asset: str, second_asset: str) -> str:
    ensure_supported_asset(payment_asset)
    ensure_supported_asset(first_asset)
    ensure_supported_asset(second_asset)
    spend_after_fee = amount * (1 - FEE_RATE)
    first_amount = spend_after_fee * DEMO_PRICES_RUB[payment_asset] / DEMO_PRICES_RUB[first_asset]
    second_amount = spend_after_fee * DEMO_PRICES_RUB[payment_asset] / DEMO_PRICES_RUB[second_asset]
    return (
        f"По демо-ценам на {format_amount(amount, payment_asset)} {ASSET_DISPLAY[payment_asset]} "
        f"после комиссии вы получите либо {format_amount(first_amount, first_asset)} {ASSET_DISPLAY[first_asset]}, "
        f"либо {format_amount(second_amount, second_asset)} {ASSET_DISPLAY[second_asset]}.\n"
        f"- {ASSET_DISPLAY[first_asset]}: {ASSET_RISK_NOTES.get(first_asset, 'Это рискованный demo asset.')}\n"
        f"- {ASSET_DISPLAY[second_asset]}: {ASSET_RISK_NOTES.get(second_asset, 'Это рискованный demo asset.')}\n"
        "Это read-only demo-ответ, не инвестиционная рекомендация."
    )

from __future__ import annotations

import json
import re
from typing import Any

from .constants import ASSET_ALIASES
from .models import ParsedIntent


JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)
NUMBER_RE = re.compile(r"(?P<value>\d[\d\s,\.]*)")
SWAP_RE = re.compile(
    r"(?:обмени|обменяй|swap(?:ни)?)\s+(?P<amount>\d[\d\s,\.]*)\s*(?P<from>[A-Za-zА-Яа-я0-9]+)\s+на\s+(?P<to>[A-Za-zА-Яа-я0-9]+)",
    re.IGNORECASE,
)
BUY_RE = re.compile(
    r"(?:купи|купить)\s+(?P<asset>[A-Za-zА-Яа-я0-9]+)\s+на\s+(?P<amount>\d[\d\s,\.]*)\s*(?P<pay>[A-Za-zА-Яа-я0-9]+)?",
    re.IGNORECASE,
)
COMPARE_RE = re.compile(
    r"что\s+выгоднее\s+купить\s+на\s+(?P<amount>\d[\d\s,\.]*)\s*(?P<pay>[A-Za-zА-Яа-я0-9]+)\s*[—\-]?\s*(?P<a>[A-Za-zА-Яа-я0-9]+)\s+или\s+(?P<b>[A-Za-zА-Яа-я0-9]+)",
    re.IGNORECASE,
)


def extract_json_payload(text: str) -> dict[str, Any]:
    stripped = text.strip()
    candidate = stripped
    if stripped.startswith("```"):
        match = JSON_BLOCK_RE.search(stripped)
        if not match:
            raise ValueError("No JSON object found in fenced content")
        candidate = match.group(0)
    return json.loads(candidate)


def normalize_asset(raw: str | None) -> str | None:
    if not raw:
        return None
    cleaned = re.sub(r"[^A-Za-zА-Яа-я0-9]", "", raw).upper()
    return ASSET_ALIASES.get(cleaned)


def parse_number(raw: str | float | int | None) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    normalized = raw.replace(" ", "").replace(",", ".")
    return float(normalized)


def intent_from_payload(payload: dict[str, Any]) -> ParsedIntent:
    return ParsedIntent(
        intent=str(payload.get("intent") or "unknown"),
        amount=parse_number(payload.get("amount")),
        payment_asset=normalize_asset(payload.get("payment_asset")),
        target_asset=normalize_asset(payload.get("target_asset")),
        compare_asset=normalize_asset(payload.get("compare_asset")),
        needs_clarification=bool(payload.get("needs_clarification", False)),
        clarifying_question=payload.get("clarifying_question"),
        assistant_summary=payload.get("assistant_summary"),
    )


def fallback_parse_intent(message_text: str) -> ParsedIntent | None:
    text = message_text.strip()
    lowered = text.lower()

    if "портф" in lowered:
        return ParsedIntent(intent="portfolio", assistant_summary="Понял запрос как просмотр портфеля.")
    if "баланс" in lowered:
        return ParsedIntent(intent="balance", assistant_summary="Понял запрос как просмотр баланса.")
    if "истор" in lowered:
        return ParsedIntent(intent="history", assistant_summary="Понял запрос как просмотр истории.")
    if "привет" in lowered or "здрав" in lowered or "что ты умеешь" in lowered or "что умеешь" in lowered:
        return ParsedIntent(intent="chat", assistant_summary="Понял запрос как обычный разговор с demo-ботом.")
    if "помощ" in lowered or lowered == "help":
        return ParsedIntent(intent="help", assistant_summary="Понял запрос как справку.")

    compare_match = COMPARE_RE.search(text)
    if compare_match:
        return ParsedIntent(
            intent="compare",
            amount=parse_number(compare_match.group("amount")),
            payment_asset=normalize_asset(compare_match.group("pay")),
            target_asset=normalize_asset(compare_match.group("a")),
            compare_asset=normalize_asset(compare_match.group("b")),
            assistant_summary="Понял запрос как demo-сравнение двух активов.",
        )

    swap_match = SWAP_RE.search(text)
    if swap_match:
        return ParsedIntent(
            intent="swap",
            amount=parse_number(swap_match.group("amount")),
            payment_asset=normalize_asset(swap_match.group("from")),
            target_asset=normalize_asset(swap_match.group("to")),
            assistant_summary="Понял запрос как демо-обмен.",
        )

    buy_match = BUY_RE.search(text)
    if buy_match:
        return ParsedIntent(
            intent="buy_asset",
            amount=parse_number(buy_match.group("amount")),
            payment_asset=normalize_asset(buy_match.group("pay")) or "RUB",
            target_asset=normalize_asset(buy_match.group("asset")),
            assistant_summary="Понял запрос как демо-покупку.",
        )

    number_match = NUMBER_RE.search(text)
    if ("купи" in lowered or "купить" in lowered) and number_match:
        asset = next((normalize_asset(token) for token in text.split() if normalize_asset(token)), None)
        if asset:
            return ParsedIntent(
                intent="buy_asset",
                amount=parse_number(number_match.group("value")),
                payment_asset=None,
                target_asset=asset,
                needs_clarification=True,
                clarifying_question="В какой валюте провести демо-покупку: RUB или USDT?",
            )

    return None

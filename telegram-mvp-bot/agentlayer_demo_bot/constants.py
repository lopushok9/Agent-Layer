from __future__ import annotations

from typing import Any

SUPPORTED_ASSETS = ("RUB", "USDT", "BTC", "SOL", "A7A5", "TSLAX", "NVDAX")

ASSET_DISPLAY = {
    "RUB": "RUB",
    "USDT": "USDT",
    "BTC": "BTC",
    "SOL": "SOL",
    "A7A5": "A7A5",
    "TSLAX": "TSLAx",
    "NVDAX": "NVDAx",
}

ASSET_ALIASES = {
    "RUB": "RUB",
    "РУБ": "RUB",
    "РУБЛ": "RUB",
    "РУБЛЕЙ": "RUB",
    "РУБЛЯ": "RUB",
    "RUR": "RUB",
    "USDT": "USDT",
    "TETHER": "USDT",
    "BTC": "BTC",
    "BITCOIN": "BTC",
    "БИТКОИН": "BTC",
    "SOL": "SOL",
    "SOLANA": "SOL",
    "СОЛ": "SOL",
    "A7A5": "A7A5",
    "TSLA": "TSLAX",
    "TSLAX": "TSLAX",
    "TESLA": "TSLAX",
    "ТЕСЛА": "TSLAX",
    "NVDA": "NVDAX",
    "NVDAX": "NVDAX",
    "NVIDIA": "NVDAX",
    "ЭНВИДИА": "NVDAX",
}

DEMO_PRICES_RUB = {
    "RUB": 1.0,
    "USDT": 100.0,
    "BTC": 8_500_000.0,
    "SOL": 15_000.0,
    "A7A5": 1.0,
    "TSLAX": 23_300.0,
    "NVDAX": 98_000.0,
}

STARTING_BALANCES = {
    "RUB": 500_000.0,
    "USDT": 5_000.0,
    "BTC": 0.0,
    "SOL": 0.0,
    "A7A5": 0.0,
    "TSLAX": 0.0,
    "NVDAX": 0.0,
}

ASSET_RISK_NOTES = {
    "BTC": "BTC в демо-портфеле можно объяснять как более зрелый и более консервативный крипто-актив.",
    "SOL": "SOL в демо-портфеле можно объяснять как более волатильный, но более growth-oriented crypto asset.",
    "TSLAX": "TSLAx в демо-портфеле стоит подавать как высокобета-токенизированный equity proxy.",
    "NVDAX": "NVDAx в демо-портфеле стоит подавать как AI-growth equity proxy с высоким уровнем ожиданий рынка.",
    "USDT": "USDT в демо-портфеле играет роль кэша и parking asset.",
    "A7A5": "A7A5 в демо-портфеле можно объяснять как low-volatility RUB-linked demo asset.",
}

FEE_RATE = 0.006
PENDING_TTL_SECONDS = 600


def model_system_prompt() -> str:
    assets = ", ".join(ASSET_DISPLAY[asset] for asset in SUPPORTED_ASSETS)
    return f"""
You are the intent parser for a Telegram demo bot called AgentLayer.

This product is a demo only:
- no real money
- no real wallets
- no blockchain execution
- no external market APIs

Supported assets:
- {assets}

Allowed intents:
- buy_asset
- swap
- portfolio
- balance
- history
- compare
- chat
- help
- unknown

Rules:
- Return JSON only.
- Do not wrap the JSON in markdown.
- If the user asks for a trade-like action but some required field is missing, set needs_clarification=true.
- buy_asset means the user spends one asset to buy a target asset.
- swap means the user converts one asset into another asset.
- compare means a read-only question comparing two assets for a budget.
- Normalize asset tickers to: RUB, USDT, BTC, SOL, A7A5, TSLAX, NVDAX.
- Use null for missing values.
- assistant_summary must be short and factual.

Required JSON shape:
{{
  "intent": "buy_asset|swap|portfolio|balance|history|compare|chat|help|unknown",
  "amount": number|null,
  "payment_asset": "RUB|USDT|BTC|SOL|A7A5|TSLAX|NVDAX"|null,
  "target_asset": "RUB|USDT|BTC|SOL|A7A5|TSLAX|NVDAX"|null,
  "compare_asset": "RUB|USDT|BTC|SOL|A7A5|TSLAX|NVDAX"|null,
  "needs_clarification": boolean,
  "clarifying_question": string|null,
  "assistant_summary": string|null
}}
""".strip()


def demo_prices_payload() -> dict[str, Any]:
    return {ASSET_DISPLAY[key]: value for key, value in DEMO_PRICES_RUB.items()}


def chat_system_prompt() -> str:
    assets = ", ".join(ASSET_DISPLAY[asset] for asset in SUPPORTED_ASSETS)
    return f"""
You are AgentLayer, a concise Telegram demo assistant for a finance product jury demo.

Important constraints:
- This is a demo only.
- No real money.
- No real wallet.
- No blockchain execution.
- No operator API.
- Prices are fixed demo prices, not live market data.

Supported assets:
- {assets}

What you should do:
- reply naturally in Russian
- be concise and interactive
- help the user understand what the bot can do
- suggest concrete next actions
- if the user asks a general product question, answer directly
- if the user asks for an operation, guide them toward a supported format
- if the user asks what the bot can do, give short examples

Tone:
- direct
- helpful
- not verbose
- not robotic

Do not:
- claim that money or onchain actions are real
- invent unsupported features
- dump large walls of text
""".strip()

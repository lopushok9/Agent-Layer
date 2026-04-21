# AgentLayer Telegram MVP Bot

Minimal Telegram demo bot for AgentLayer.

What it does:

- creates a demo user on `/start`
- keeps a virtual portfolio in SQLite
- uses OpenRouter to parse natural-language intents
- falls back to a local parser for core `swap` and `buy` flows
- shows `preview -> confirm -> execute`
- stores balance changes and transaction history

What it does not do:

- real money
- wallets
- onchain execution
- external market data
- external business APIs

## Run

```bash
cd telegram-mvp-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN="..."
export OPENROUTER_API_KEY="..."
export OPENROUTER_MODEL="openai/gpt-4o-mini"
python -m agentlayer_demo_bot
```

The bot also accepts env aliases:

- `BOT_TOKEN` instead of `TELEGRAM_BOT_TOKEN`
- `OPENROUTER_KEY` instead of `OPENROUTER_API_KEY`

Optional:

```bash
export DEMO_DB_PATH="./demo-bot.sqlite3"
```

## Railway

You can deploy this bot to Railway now.

Recommended setup:

- create a `Worker` service
- set the root directory to `telegram-mvp-bot`
- set env vars:
  - `TELEGRAM_BOT_TOKEN`
  - `OPENROUTER_API_KEY`
  - `OPENROUTER_MODEL`
- attach a volume if you want SQLite state to survive redeploys
- if you attach a volume at `/data`, set `DEMO_DB_PATH=/data/demo-bot.sqlite3`

Notes:

- this bot uses long polling, not webhooks
- no public HTTP port is required
- without a mounted volume, SQLite state will reset after restart/redeploy
- `Procfile` and `nixpacks.toml` are already included for Railway

## Commands

- `/start`
- `/help`
- `/balance`
- `/portfolio`
- `/history`
- `/reset`

## Supported write messages

- `Обмени 10000 RUB на USDT`
- `Купи BTC на 25000 RUB`
- `Купи TSLAx на 50000 RUB`

## Demo rules

- fixed fee: `0.6%`
- fixed demo prices
- amount is treated as total spend from the source asset
- fee is included inside the spend amount
- one active pending action per user
- pending action expires in 10 minutes

## Reliability notes

The bot uses OpenRouter for intent extraction and short conversational responses.
Portfolio math, balances, confirm flow, and history are always handled locally.

If OpenRouter returns invalid JSON or is temporarily unavailable, the bot falls
back to a local regex parser for the main demo paths.

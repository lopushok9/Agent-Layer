---
description: Pay a card-only merchant from the operator's shared Airwallex account with a single-use virtual card issued for this one purchase (sandbox).
argument-hint: "[amount] [merchant] — [purpose]"
allowed-tools: AskUserQuestion, mcp__plugin_wallet_agent-wallet__treasury_my_budget, mcp__plugin_wallet_agent-wallet__treasury_request_payment, mcp__plugin_wallet_agent-wallet__treasury_payment_status, mcp__plugin_wallet_agent-wallet__treasury_simulate_charge, mcp__plugin_wallet_agent-wallet__treasury_cancel_payment, mcp__agentlayer-treasury__treasury_my_budget, mcp__agentlayer-treasury__treasury_request_payment, mcp__agentlayer-treasury__treasury_payment_status, mcp__agentlayer-treasury__treasury_simulate_charge, mcp__agentlayer-treasury__treasury_cancel_payment
disable-model-invocation: true
---

# Card pay (Airwallex, single-use card per purchase)

Arguments: `$ARGUMENTS`

The money belongs to the operator's shared Airwallex account, and the treasury policy decides in code. This
command proposes one purchase and walks it through. It runs against the **Airwallex sandbox** only, and no real
money moves.

Never ask for, display, log or type a card number, CVV or expiry. You only ever get `last4` and a `vault_reference`.

## 1. Collect the purchase

Read the amount, merchant and purpose from the arguments. Any missing piece is asked with **one**
`AskUserQuestion` call:

- amount in USD with at most two decimals
- merchant name
- purpose (one line saying what is bought and why)
- merchant category, with options `5734 Software`, `7372 Cloud / IT services`, `5817 Digital goods`. "Other" takes a 4-digit MCC.

Never split one purchase into several to stay under a limit.

## 2. Check the budget

Call `treasury_my_budget`. If `status` is not `active`, or `available` is below the amount, stop and say so.
Also say whether the amount is within `auto_approve_limit`, in which case the card is issued at once, or will wait for the operator.

## 3. Confirm

Call `AskUserQuestion` with header `Confirm` and this question:
`Request a single-use Airwallex card for $<amount> at <merchant> (<mcc>) for "<purpose>"?`
The options are `Request` and `Cancel`. Continue only on `Request`.

## 4. Request the card

Call `treasury_request_payment` with `merchant`, `amount`, `purpose`, `mcc` and `accepts_x402: false`. This command is
the card rail. For merchants that may accept x402, use the normal `treasury_request_payment` flow with `merchant_url`.

Act on `status`:

- `card_issued`: show a short table with payment id, card `•••• last4`, limit, merchant categories, single use
  and `active_to`. Go to step 5.
- `pending_approval`: show `decision.reasons` and tell the user the operator approves it in the dashboard
  (`agent-wallet/scripts/treasury dashboard`) or with `agent-wallet/scripts/treasury approve <payment_id>`. Do not
  retry with a different amount. Stop. Re-run step 4's status check with `treasury_payment_status` only if asked.
- `denied`: explain `decision.reasons` and stop. Do not try another merchant or rail to get around it.

## 5. Merchant charge (sandbox)

Ask with `AskUserQuestion` (header `Charge`): `Run the merchant's charge of $<amount> against card •••• <last4> now?`
The options are `Charge` and `Cancel purchase`.

- `Charge` → `treasury_simulate_charge` with `payment_id`. Report `process_result` and the payment status.
  `APPROVED` means the payment is `settled`. A decline (`LIMIT_EXCEEDED`, `MERCHANT_CATEGORY_NOT_ALLOWED`,
  `CARD_CLOSED`, `OUT_OF_ALLOWED_TIME_RANGE`) means the merchant charged something other than what was approved.
  Report it, and note that a different total needs a new request.
- `Cancel purchase` → `treasury_cancel_payment`. The card is closed and the reservation released.

In production, step 5 is the real checkout. `use_saved_card` with the `vault_reference` either sends a fixed HTTPS
request or drives a managed Kernel browser that fills the card fields itself, and the merchant's authorization hits
the same Airwallex card controls.

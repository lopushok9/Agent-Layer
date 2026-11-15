---
name: agent-treasury
description: "Use when an agent must pay for something for the business from the operator's shared account — buy a dataset, API access, compute, a SaaS seat, pay a vendor — or asks about its budget. Trigger phrases include \"buy\", \"purchase\", \"pay for\", \"subscribe\", \"my budget\", \"how much can I spend\", \"company card\", \"Airwallex\". Uses treasury_* tools: x402 first, otherwise a single-use Airwallex card under the operator's policy."
user-invocable: false
---

# Agent Treasury (shared Airwallex account)

You spend the operator's money, not your own. The treasury decides in code; you propose and explain.

1. `treasury_my_budget` → check `available`, `per_tx_limit`, `auto_approve_limit`, allowed `rails` and `allowed_mcc`
   before planning a purchase. Never split one purchase into several to stay under a limit.
2. `treasury_request_payment` with `merchant`, exact `amount`, a clear `purpose`, the merchant's `merchant_url`
   when you have it (used to detect x402) and the `mcc` (5734 software, 7372 cloud/IT, 5817 digital goods).
3. Act on `status`:
   - `x402_ready` → pay with `x402_preview_request` / `x402_pay_request` on that URL (show the preview first),
     then `treasury_record_x402` with `settled` + amount + transaction, or `failed`.
   - `card_issued` → you hold only `card.last4` and `card.vault_reference`. Check out with
     `use_saved_card(vault_reference=..., checkout=...)` or its HTTPS `request` mode. Never ask for, print or type card
     numbers. In the sandbox, `treasury_checkout(payment_id, checkout_url)` pays a local test merchant's checkout form
     (the treasury fills it from the vault), and `treasury_simulate_charge` runs a bare merchant authorization.
   - `pending_approval` → tell the user what the operator must approve and why (`decision.reasons`). Do not retry
     or change the amount to dodge the policy. Poll `treasury_payment_status` only when asked.
   - `denied` → stop and explain. Do not try another rail or merchant to get around it.
4. An Airwallex decline (`LIMIT_EXCEEDED`, `MERCHANT_CATEGORY_NOT_ALLOWED`, `CARD_CLOSED`) means the merchant asked
   for something other than what was approved. Report it; a different total needs a new request.
5. If a purchase is abandoned, call `treasury_cancel_payment` so the card is closed and the budget released.

The operator approves, changes limits and pauses agents with the `treasury` CLI or dashboard. You cannot.

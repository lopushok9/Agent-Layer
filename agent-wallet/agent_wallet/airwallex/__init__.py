"""Airwallex treasury layer: shared account, per-agent budgets, x402-first routing
with a fiat fallback through single-purpose Airwallex Issuing cards.

Sandbox only by default. Card PAN/CVV go from Airwallex straight into the local
encrypted CardVault; agents only ever see an opaque vault reference.
"""

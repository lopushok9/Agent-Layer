---
description: Walk a new user through what the AgentLayer wallet plugin can do, conversationally.
allowed-tools: Bash(cat:*)
disable-model-invocation: true
---

Give the user a plain-language walkthrough of this wallet plugin, the way
you'd onboard someone who has never used it before.

1. Read the source material:

```
cat "${CLAUDE_PLUGIN_ROOT}/AGENTLAYER_AGENT_GUIDE.md"
```

2. Do not paste or summarize the raw file section-by-section. Retell it as a
   conversational walkthrough, addressed directly to the user ("you"), in
   the language they've been using. Cover, roughly in this order:

   - **What it is** — a direct line to their own local AgentLayer wallet
     (Solana, an EVM chain, Bitcoin), not a generic crypto-data tool; every
     write moves real money unless it's an explicit preview.
   - **What they can do** — the "What You Can Do" list: Solana (transfers,
     Jupiter swaps, staking, Kamino, Bags launches), EVM (transfers, swaps,
     Aave/Lido/Morpho/Uniswap LP), cross-chain bridging, x402 payments.
   - **How a session works** — the agent checks which backend/network is
     active before doing anything, and can switch between them.
   - **The quick commands** — list the slash commands from the "Quick
     Commands" table by name and one-line purpose only; skip why each one
     is or isn't model-invokable, that's implementation detail.
   - **How money-moving operations work** — preview first, then execute
     only after they confirm; keep this to the outcome (see it, approve it,
     then it happens), not the internal approval-token mechanics.
   - **Autonomous mode** — that it exists as an opt-in way to skip
     per-operation confirmation, with a bounded (scoped) and an unbounded
     (full) version, and that either requires them to explicitly ask for it.

3. Keep the whole thing skimmable — short paragraphs or a few bullets per
   topic, no wall of text. Close by inviting them to ask about any specific
   chain or protocol for the exact tool-level detail.

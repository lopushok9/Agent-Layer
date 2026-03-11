# Product Page Design
**Date:** 2026-02-19
**Status:** Approved

## Vision
A narrative scroll page presenting AgentLayer as infrastructure for agentic finance. Same visual language as the landing: Inter, #111213, white, tight letter-spacing, large bold typography.

## Structure

### 1. Hero (100vh)
- Same header (AgentLayer nav, Download button)
- Small label: `Product` — 12px, uppercase, #5f6368
- Headline: `Infrastructure for agentic finance` — ~40px, 700 weight
- Subtext: 2-3 lines, meta-layer positioning, AI agents context
- Status badge: `Building` with pulsing dot — signals active development

### 2. Feature Sections (4 × ~80–100vh)
Each section separated by a thin horizontal rule. Layout per section:
- Number anchor (`01`–`04`) — 12px, left edge
- Feature name — large type, ~7–8vw, 800 weight, left
- Description — 14px, 2–3 lines, right side
- Technical tag — data source + cache TTL, 12px, gray

| # | Name | Source | Cache |
|---|------|--------|-------|
| 01 | Real-time prices | CoinGecko → CoinCap | 30s |
| 02 | DeFi intelligence | DeFiLlama | 5–10min |
| 03 | On-chain analytics | PublicNode RPC + Alchemy + Etherscan | 2min |
| 04 | AI Agent identity | ERC-8004 IdentityRegistry | 2min |

### 3. Footer section
Same style as landing bottom: large type + footer links.

## Design Tokens (inherit from Interface.css)
- Font: Inter
- Color: #111213 (primary), #5f6368 (secondary), #ffffff (bg)
- Font weights: 800 (display), 700 (title), 500 (nav), 400 (body)
- Letter-spacing: -0.04em (display), -0.02em (title), -0.01em (body)
- Padding: 40px horizontal (desktop), 20px (mobile)
- Animations: fadeIn, fadeInUp (inherit existing keyframes)

## Files
- `src/components/ProductPage.jsx` — new component
- `src/styles/ProductPage.css` — new styles (extend design tokens)
- `src/App.jsx` — add routing or conditional render

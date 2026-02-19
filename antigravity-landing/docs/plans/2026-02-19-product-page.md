# Product Page Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Product page in the same visual style as the landing — narrative scroll, large typography, minimal — accessible via the "Product" nav link.

**Architecture:** Hash-based routing (`#product` / `#home`) in App.jsx, no new dependencies. ProductPage is a standalone component with its own CSS that inherits the design tokens from index.css. Particles background renders on both pages.

**Tech Stack:** React 19, Vite, Inter font, plain CSS (same patterns as Interface.css)

---

### Task 1: Hash-based routing in App.jsx

**Files:**
- Modify: `src/App.jsx`

**Step 1: Add route state to App.jsx**

Replace the current App.jsx content with:

```jsx
import { useState, useEffect } from 'react'
import { Particles } from './components/Particles'
import { Interface } from './components/Interface'
import { ProductPage } from './components/ProductPage'
import './index.css'

function App() {
  const [page, setPage] = useState(
    window.location.hash === '#product' ? 'product' : 'home'
  )

  useEffect(() => {
    const onHash = () => {
      setPage(window.location.hash === '#product' ? 'product' : 'home')
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  return (
    <>
      <Particles />
      {page === 'product' ? <ProductPage /> : <Interface />}
    </>
  )
}

export default App
```

**Step 2: Update Product nav link in Interface.jsx**

In `src/components/Interface.jsx`, find all occurrences of:
```jsx
<a href="#" className="nav-item">Product</a>
```
and change `href="#"` to `href="#product"`.

Also update the mobile nav link:
```jsx
<a href="#product" className="mobile-nav-link">Product</a>
```

**Step 3: Verify in browser**
- Run `npm run dev`
- Click "Product" in nav → URL becomes `/#product`, product page renders
- Click browser back → returns to home

**Step 4: Commit**
```bash
git add src/App.jsx src/components/Interface.jsx
git commit -m "feat: add hash-based routing for Product page"
```

---

### Task 2: ProductPage component — scaffold + header

**Files:**
- Create: `src/components/ProductPage.jsx`
- Create: `src/styles/ProductPage.css`

**Step 1: Create ProductPage.jsx with header**

```jsx
import '../styles/ProductPage.css'

export const ProductPage = () => {
  return (
    <div className="product-page">

      {/* Header — same as Interface */}
      <header className="pp-header">
        <div className="pp-brand">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
            <path d="M12 2L2 7L12 12L22 7L12 2Z" fill="#111213" />
            <path d="M2 17L12 22L22 17" stroke="#111213" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M2 12L12 17L22 12" stroke="#111213" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <span className="pp-brand-text">AgentLayer</span>
        </div>

        <nav className="pp-nav">
          <a href="#" className="pp-nav-item">
            Product
            <svg className="pp-chevron" width="10" height="6" viewBox="0 0 10 6" fill="none">
              <path d="M1 1L5 5L9 1" stroke="#111213" strokeOpacity="0.8" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </a>
          <a href="#" className="pp-nav-item">Use Cases</a>
          <a href="#" className="pp-nav-item">Pricing</a>
          <a href="#" className="pp-nav-item">Blog</a>
          <a href="#" className="pp-nav-item">
            Resources
            <svg className="pp-chevron" width="10" height="6" viewBox="0 0 10 6" fill="none">
              <path d="M1 1L5 5L9 1" stroke="#111213" strokeOpacity="0.8" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </a>
        </nav>

        <a href="#" className="pp-btn-home">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <path d="M7 13V5M7 5L4 8M7 5L10 8" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M1 1H13" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          Download
        </a>
      </header>

      {/* Content placeholder — filled in Task 3 */}
      <main className="pp-main" />
    </div>
  )
}
```

**Step 2: Create ProductPage.css — base + header styles**

```css
.product-page {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  min-height: 100vh;
  color: #111213;
  font-family: 'Inter', sans-serif;
}

/* Header */
.pp-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  height: 72px;
  padding: 0 32px;
  box-sizing: border-box;
  animation: fadeIn 0.8s ease-out forwards;
  opacity: 0;
  animation-delay: 0.1s;
}

.pp-brand {
  display: flex;
  align-items: center;
  gap: 12px;
}

.pp-brand-text {
  font-size: 14px;
  font-weight: 500;
  letter-spacing: -0.01em;
  color: #111213;
}

.pp-nav {
  display: flex;
  gap: 28px;
  align-items: center;
}

.pp-nav-item {
  text-decoration: none;
  color: #111213;
  font-weight: 500;
  font-size: 14px;
  letter-spacing: -0.01em;
  display: flex;
  align-items: center;
  gap: 6px;
  transition: opacity 0.2s;
}

.pp-nav-item:hover {
  text-decoration: underline;
  text-decoration-thickness: 1px;
  text-underline-offset: 3px;
  opacity: 0.8;
}

.pp-chevron { opacity: 0.8; }

.pp-btn-home {
  background: #111213;
  color: #ffffff;
  text-decoration: none;
  border: none;
  height: 38px;
  padding: 0 16px;
  border-radius: 999px;
  font-size: 14px;
  font-weight: 600;
  letter-spacing: -0.01em;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 8px;
  transition: background 0.2s;
}

.pp-btn-home:hover { background: #1a1b1f; }

/* Shared animations (mirror index.css) */
@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(24px); }
  to { opacity: 1; transform: translateY(0); }
}
```

**Step 3: Verify header looks identical to landing header**
- `npm run dev`, navigate to `/#product`
- Header should match Interface.jsx visually

**Step 4: Commit**
```bash
git add src/components/ProductPage.jsx src/styles/ProductPage.css
git commit -m "feat: ProductPage scaffold with header"
```

---

### Task 3: Hero / Manifesto section

**Files:**
- Modify: `src/components/ProductPage.jsx` — replace `<main className="pp-main" />`
- Modify: `src/styles/ProductPage.css` — append hero styles

**Step 1: Replace `<main>` with hero markup**

```jsx
<main className="pp-main">

  {/* Hero */}
  <section className="pp-hero">
    <div className="pp-hero-inner">
      <span className="pp-label">Product</span>
      <h1 className="pp-hero-headline">
        Infrastructure for<br />agentic finance
      </h1>
      <p className="pp-hero-sub">
        AgentLayer is the finance meta-layer for AI agents —
        a protocol-level stack that lets autonomous systems
        read markets, query chains, and understand DeFi
        without building their own data pipelines.
      </p>
      <div className="pp-status">
        <span className="pp-status-dot" />
        Building
      </div>
    </div>
  </section>

  {/* Feature sections placeholder — filled in Task 4 */}

</main>
```

**Step 2: Append hero styles to ProductPage.css**

```css
/* Hero */
.pp-main {
  width: 100%;
}

.pp-hero {
  min-height: calc(100vh - 72px);
  display: flex;
  align-items: center;
  padding: 0 40px;
  box-sizing: border-box;
}

.pp-hero-inner {
  max-width: 800px;
  animation: fadeInUp 0.9s ease-out forwards;
  opacity: 0;
  animation-delay: 0.3s;
}

.pp-label {
  display: block;
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #5f6368;
  margin-bottom: 24px;
}

.pp-hero-headline {
  font-size: clamp(40px, 5.5vw, 80px);
  font-weight: 800;
  letter-spacing: -0.04em;
  line-height: 0.95;
  color: #111213;
  margin: 0 0 28px 0;
}

.pp-hero-sub {
  font-size: 16px;
  font-weight: 400;
  line-height: 1.6;
  color: #5f6368;
  max-width: 520px;
  margin: 0 0 32px 0;
  letter-spacing: -0.005em;
}

.pp-status {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 500;
  color: #111213;
  letter-spacing: -0.01em;
}

.pp-status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #111213;
  animation: pulse 2s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.4; transform: scale(0.85); }
}
```

**Step 3: Verify hero looks correct**
- Full-height section, left-aligned
- Headline spans 2 lines, ~5.5vw clamped
- "Building" with pulsing dot visible

**Step 4: Commit**
```bash
git add src/components/ProductPage.jsx src/styles/ProductPage.css
git commit -m "feat: ProductPage hero section with manifesto"
```

---

### Task 4: Feature sections (01–04)

**Files:**
- Modify: `src/components/ProductPage.jsx` — add features after hero
- Modify: `src/styles/ProductPage.css` — append feature styles

**Step 1: Add features data array and render loop in ProductPage.jsx**

Add this constant before the return statement:

```jsx
const FEATURES = [
  {
    num: '01',
    name: 'Real-time prices',
    description: 'Batch queries up to 50 symbols in a single call. Automatic fallback chain keeps data flowing when primary sources hit limits.',
    source: 'CoinGecko → CoinCap',
    cache: '30s TTL',
  },
  {
    num: '02',
    name: 'DeFi intelligence',
    description: 'Protocol TVL, pool yields, fees and revenue, stablecoin supply — every metric an agent needs to reason about DeFi.',
    source: 'DeFiLlama',
    cache: '5–10min TTL',
  },
  {
    num: '03',
    name: 'On-chain analytics',
    description: 'Native balances, ERC-20 portfolios, transaction history and gas prices across six chains — via public RPC with no key required.',
    source: 'PublicNode · Alchemy · Etherscan',
    cache: '2min TTL',
  },
  {
    num: '04',
    name: 'AI agent identity',
    description: 'Resolve ERC-8004 agent tokens to their on-chain owner, linked wallet and metadata URI. The identity layer for autonomous finance.',
    source: 'ERC-8004 IdentityRegistry',
    cache: '2min TTL',
  },
]
```

Then replace the `{/* Feature sections placeholder */}` comment with:

```jsx
  {/* Features */}
  <section className="pp-features">
    {FEATURES.map((f, i) => (
      <div className="pp-feature" key={f.num}>
        <div className="pp-feature-inner">
          <span className="pp-feature-num">{f.num}</span>
          <h2 className="pp-feature-name">{f.name}</h2>
          <p className="pp-feature-desc">{f.description}</p>
          <div className="pp-feature-tags">
            <span className="pp-tag">{f.source}</span>
            <span className="pp-tag">{f.cache}</span>
          </div>
        </div>
      </div>
    ))}
  </section>
```

**Step 2: Append feature styles to ProductPage.css**

```css
/* Features */
.pp-features {
  width: 100%;
}

.pp-feature {
  padding: 80px 40px;
  border-top: 1px solid rgba(17, 18, 19, 0.1);
  box-sizing: border-box;
}

.pp-feature-inner {
  max-width: 100%;
  display: grid;
  grid-template-columns: 48px 1fr;
  grid-template-rows: auto auto auto;
  column-gap: 0;
  row-gap: 0;
}

.pp-feature-num {
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.06em;
  color: #5f6368;
  padding-top: 12px;
  line-height: 1;
}

.pp-feature-name {
  font-size: clamp(36px, 6.5vw, 96px);
  font-weight: 800;
  letter-spacing: -0.04em;
  line-height: 0.9;
  color: #111213;
  margin: 0 0 28px 0;
  grid-column: 2;
}

.pp-feature-desc {
  font-size: 15px;
  font-weight: 400;
  line-height: 1.65;
  color: #5f6368;
  max-width: 480px;
  margin: 0 0 24px 0;
  letter-spacing: -0.005em;
  grid-column: 2;
}

.pp-feature-tags {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  grid-column: 2;
}

.pp-tag {
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.02em;
  color: #5f6368;
  border: 1px solid rgba(17, 18, 19, 0.15);
  border-radius: 999px;
  padding: 4px 10px;
}
```

**Step 3: Verify all 4 features render correctly**
- Each separated by thin top border
- Feature name is large (6.5vw clamped)
- Number `01`–`04` aligned to left edge

**Step 4: Commit**
```bash
git add src/components/ProductPage.jsx src/styles/ProductPage.css
git commit -m "feat: ProductPage feature sections 01-04"
```

---

### Task 5: Footer section (same style as landing bottom)

**Files:**
- Modify: `src/components/ProductPage.jsx` — add footer after features
- Modify: `src/styles/ProductPage.css` — append footer styles

**Step 1: Add footer markup after `</section>` closing features**

```jsx
  {/* Footer */}
  <div className="pp-footer-section">
    <div className="pp-footer-header">
      <h2 className="pp-footer-title">finance</h2>
      <div className="pp-footer-links">
        <div className="pp-link-col">
          <a href="#">Download</a>
          <a href="#">Product</a>
          <a href="#">Docs</a>
          <a href="#">Changelog</a>
          <a href="#">Press</a>
          <a href="#">Releases</a>
        </div>
        <div className="pp-link-col">
          <a href="#">Blog</a>
          <a href="#">Pricing</a>
          <a href="#">Use Cases</a>
        </div>
      </div>
    </div>

    <div className="pp-footer-huge">
      <h1 className="pp-huge-text">for ai agents</h1>
    </div>

    <div className="pp-footer-bottom">
      <div className="pp-footer-brand">Agent Layer</div>
      <div className="pp-footer-bottom-links">
        <a href="#">About Agent Layer</a>
        <a href="#">Agent Layer Products</a>
        <a href="#">Privacy</a>
        <a href="#">Terms</a>
      </div>
    </div>
  </div>
```

**Step 2: Append footer styles to ProductPage.css**

```css
/* Footer section — mirrors landing extended-section */
.pp-footer-section {
  padding: 8vh 40px 4vh;
  box-sizing: border-box;
  border-top: 1px solid rgba(17, 18, 19, 0.1);
  display: flex;
  flex-direction: column;
}

.pp-footer-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  width: 100%;
}

.pp-footer-title {
  font-size: 14.5vw;
  font-weight: 800;
  letter-spacing: -0.04em;
  line-height: 0.88;
  margin: 0;
  color: #111213;
}

.pp-footer-links {
  display: flex;
  gap: 80px;
}

.pp-link-col {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.pp-link-col a,
.pp-footer-bottom-links a {
  text-decoration: none;
  color: #111213;
  font-size: 14px;
  font-weight: 500;
  letter-spacing: -0.01em;
  transition: opacity 0.2s;
}

.pp-link-col a:hover,
.pp-footer-bottom-links a:hover {
  text-decoration: underline;
  text-decoration-thickness: 1px;
}

.pp-footer-huge {
  width: 100%;
  margin-top: 0;
  margin-bottom: 4vh;
}

.pp-huge-text {
  font-size: 14.5vw;
  font-weight: 800;
  letter-spacing: -0.04em;
  line-height: 0.88;
  color: #111213;
  margin: 0;
  text-align: left;
  white-space: nowrap;
}

.pp-footer-bottom {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  padding-top: 0;
  padding-bottom: 20px;
  width: 100%;
}

.pp-footer-brand {
  font-size: 24px;
  font-weight: 500;
  color: #111213;
  letter-spacing: -0.03em;
}

.pp-footer-bottom-links {
  display: flex;
  gap: 24px;
}

.pp-footer-bottom-links a {
  font-weight: 400;
  font-size: 14px;
  opacity: 0.8;
}
```

**Step 3: Verify footer matches landing bottom section**
- "finance" same size as landing, aligned left with links on right
- "for ai agents" huge text below
- Bottom bar with brand + links

**Step 4: Commit**
```bash
git add src/components/ProductPage.jsx src/styles/ProductPage.css
git commit -m "feat: ProductPage footer section"
```

---

### Task 6: Mobile responsive

**Files:**
- Modify: `src/styles/ProductPage.css` — append mobile breakpoint

**Step 1: Append mobile breakpoint**

```css
@media (max-width: 768px) {
  .pp-header {
    height: 64px;
    padding: 0 20px;
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    background: #ffffff;
    z-index: 200;
  }

  .pp-nav { display: none; }
  .pp-btn-home { display: none; }

  .pp-hero {
    padding: 0 20px;
    padding-top: 64px;
  }

  .pp-feature {
    padding: 60px 20px;
  }

  .pp-feature-inner {
    grid-template-columns: 36px 1fr;
  }

  .pp-footer-section {
    padding: 60px 20px 40px;
  }

  .pp-footer-header {
    flex-direction: column;
    gap: 40px;
  }

  .pp-footer-links {
    flex-direction: column;
    gap: 32px;
  }

  .pp-footer-bottom {
    flex-direction: column;
    align-items: flex-start;
    gap: 24px;
  }

  .pp-footer-bottom-links {
    flex-direction: column;
    gap: 12px;
  }
}
```

**Step 2: Test on mobile viewport**
- Chrome DevTools → 375px width
- Header fixed, nav hidden
- Features readable, footer stacked

**Step 3: Final commit**
```bash
git add src/styles/ProductPage.css
git commit -m "feat: ProductPage mobile responsive"
```

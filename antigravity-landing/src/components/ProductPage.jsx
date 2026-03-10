import '../styles/ProductPage.css'

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

export const ProductPage = () => {
  return (
    <div className="product-page">

      {/* Header */}
      <header className="pp-header">
        <a href="#" className="pp-brand">
          <img src="/apple-touch-icon.png" alt="AgentLayer logo" className="pp-brand-mark" />
          <span className="pp-brand-text">AgentLayer</span>
        </a>

        <nav className="pp-nav">
          <a href="#product" className="pp-nav-item pp-nav-active">Product</a>
          <a href="#use-cases" className="pp-nav-item">Use Cases</a>
          <a href="#how-to-use" className="pp-nav-item">How to use</a>
          <a href="#about-agent-layer" className="pp-nav-item">About</a>
        </nav>

        <a href="#" className="pp-btn-cta">
          Install
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M7 1V9M7 9L4 6M7 9L10 6" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M1 13H13" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </a>
      </header>

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
              beta version
            </div>
          </div>
        </section>

        {/* Features */}
        <section className="pp-features">
          {FEATURES.map((f) => (
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

        {/* Footer */}
        <div className="pp-footer-section">
          <div className="pp-footer-header">
            <h2 className="pp-footer-title">finance</h2>
            <div className="pp-footer-links">
              <div className="pp-link-col">
                <a href="#product">Product</a>
                <a href="#use-cases">Use Cases</a>
                <a href="#how-to-use">How to use</a>
              </div>
              <div className="pp-link-col">
                <a href="https://github.com" target="_blank" rel="noreferrer">GitHub</a>
                <a href="#">Blog</a>
              </div>
            </div>
          </div>

          <div className="pp-footer-huge">
            <h1 className="pp-huge-text">for ai agents</h1>
          </div>

          <div className="pp-footer-bottom">
            <div className="pp-footer-brand">Agent Layer</div>
            <div className="pp-footer-bottom-links">
              <a href="#about-agent-layer">About Agent Layer</a>
              <a href="#terms">Terms</a>
            </div>
          </div>
        </div>

      </main>
    </div>
  )
}

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
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
            <path d="M12 2L2 7L12 12L22 7L12 2Z" fill="#111213" />
            <path d="M2 17L12 22L22 17" stroke="#111213" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M2 12L12 17L22 12" stroke="#111213" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <span className="pp-brand-text">AgentLayer</span>
        </a>

        <nav className="pp-nav">
          <a href="#product" className="pp-nav-item pp-nav-active">Product</a>
          <a href="#use-cases" className="pp-nav-item">Use Cases</a>
          <a href="#how-to-use" className="pp-nav-item">How to use</a>
          <a href="#" className="pp-nav-item">Resources</a>
        </nav>

        <a href="#" className="pp-btn-cta">Download</a>
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
              <a href="#">Terms</a>
            </div>
          </div>
        </div>

      </main>
    </div>
  )
}

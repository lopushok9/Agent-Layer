import '../styles/UseCasesPage.css'

const USE_CASES = [
  {
    num: '01',
    name: 'Portfolio agent',
    description: 'An agent that monitors wallets in real time — native balances, ERC-20 holdings, transaction history and portfolio value in USD across six chains.',
    tools: ['get_wallet_portfolio', 'get_token_transfers', 'get_crypto_prices'],
  },
  {
    num: '02',
    name: 'DeFi yield optimizer',
    description: 'An agent that scans every live pool, compares APY across protocols and chains, filters by TVL and risk, and surfaces the best strategy for a given risk profile.',
    tools: ['get_defi_yields', 'get_protocol_tvl', 'get_protocol_fees'],
  },
  {
    num: '03',
    name: 'On-chain analyst',
    description: 'An agent that reads the state of the network: gas across chains, stablecoin supply shifts, protocol activity and global market conditions — all in a single context window.',
    tools: ['get_gas_prices', 'get_stablecoin_stats', 'get_market_overview'],
  },
  {
    num: '04',
    name: 'Agent economy',
    description: 'Agents discover other agents through the ERC-8004 on-chain registry. Each registered agent has a wallet, metadata and a declared set of tasks it performs — the foundation of an autonomous agent economy.',
    tools: ['get_agent_by_id'],
  },
]

export const UseCasesPage = () => {
  return (
    <div className="uc-page">

      {/* Header */}
      <header className="uc-header">
        <a href="#" className="uc-brand">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
            <path d="M12 2L2 7L12 12L22 7L12 2Z" fill="#111213" />
            <path d="M2 17L12 22L22 17" stroke="#111213" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M2 12L12 17L22 12" stroke="#111213" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <span className="uc-brand-text">AgentLayer</span>
        </a>

        <nav className="uc-nav">
          <a href="#product" className="uc-nav-item">Product</a>
          <a href="#use-cases" className="uc-nav-item uc-nav-active">Use Cases</a>
          <a href="#how-to-use" className="uc-nav-item">How to use</a>
          <a href="#" className="uc-nav-item">Resources</a>
        </nav>

        <a href="#" className="uc-btn-cta">Download</a>
      </header>

      <main className="uc-main">

        {/* Hero */}
        <section className="uc-hero">
          <div className="uc-hero-inner">
            <span className="uc-label">Use Cases</span>
            <h1 className="uc-hero-headline">
              What agents build<br />with AgentLayer
            </h1>
            <p className="uc-hero-sub">
              Four scenarios — from real-time portfolio monitoring
              to an autonomous DeFi strategy engine and
              a self-sovereign agent with on-chain identity.
            </p>
          </div>
        </section>

        {/* Use cases */}
        <section className="uc-cases">
          {USE_CASES.map((c) => (
            <div className="uc-case" key={c.num}>
              <div className="uc-case-inner">
                <span className="uc-case-num">{c.num}</span>
                <h2 className="uc-case-name">{c.name}</h2>
                <p className="uc-case-desc">{c.description}</p>
                <div className="uc-case-tags">
                  {c.tools.map((t) => (
                    <span className="uc-tag" key={t}>{t}</span>
                  ))}
                </div>
              </div>
            </div>
          ))}
        </section>

        {/* Footer */}
        <div className="uc-footer-section">
          <div className="uc-footer-header">
            <h2 className="uc-footer-title">finance</h2>
            <div className="uc-footer-links">
              <div className="uc-link-col">
                <a href="#">Download</a>
                <a href="#">Product</a>
                <a href="#">Docs</a>
                <a href="#">Changelog</a>
                <a href="#">Press</a>
                <a href="#">Releases</a>
              </div>
              <div className="uc-link-col">
                <a href="#">Blog</a>
                <a href="#">Pricing</a>
                <a href="#use-cases">Use Cases</a>
              </div>
            </div>
          </div>

          <div className="uc-footer-huge">
            <h1 className="uc-huge-text">for ai agents</h1>
          </div>

          <div className="uc-footer-bottom">
            <div className="uc-footer-brand">Agent Layer</div>
            <div className="uc-footer-bottom-links">
              <a href="#">About Agent Layer</a>
              <a href="#">Agent Layer Products</a>
              <a href="#">Privacy</a>
              <a href="#">Terms</a>
            </div>
          </div>
        </div>

      </main>
    </div>
  )
}

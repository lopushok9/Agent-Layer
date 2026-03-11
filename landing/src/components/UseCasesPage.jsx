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
  {
    num: '05',
    name: 'Agent DAO creation',
    description: 'Agents can find each other, study reputation, evaluate the services they offer, and coordinate into agent-native DAOs. A future agent economy cannot exist without this discovery and coordination layer.',
    tools: ['get_agent_by_id'],
  },
]

export const UseCasesPage = ({ onInstallClick }) => {
  return (
    <div className="uc-page">

      {/* Header */}
      <header className="uc-header">
        <a href="#" className="uc-brand" target="_blank" rel="noreferrer">
          <img src="/apple-touch-icon.png" alt="AgentLayer logo" className="uc-brand-mark" />
          <span className="uc-brand-text">AgentLayer</span>
        </a>

        <nav className="uc-nav">
          <a href="#product" className="uc-nav-item" target="_blank" rel="noreferrer">Product</a>
          <a href="#use-cases" className="uc-nav-item uc-nav-active" target="_blank" rel="noreferrer">Use Cases</a>
          <a href="#how-to-use" className="uc-nav-item" target="_blank" rel="noreferrer">How to use</a>
          <a href="#about-agent-layer" className="uc-nav-item" target="_blank" rel="noreferrer">About</a>
        </nav>

        <a href="#" className="uc-btn-cta" onClick={(event) => {
          event.preventDefault()
          onInstallClick()
        }}>
          Install
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M7 1V9M7 9L4 6M7 9L10 6" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M1 13H13" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </a>
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
              Five scenarios — from real-time portfolio monitoring
              to an autonomous DeFi strategy engine and
              agent-native coordination through the ERC-8004 identity layer.
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
                <a href="#product" target="_blank" rel="noreferrer">Product</a>
                <a href="#use-cases" target="_blank" rel="noreferrer">Use Cases</a>
                <a href="#how-to-use" target="_blank" rel="noreferrer">How to use</a>
              </div>
              <div className="uc-link-col">
                <a href="https://github.com/lopushok9/Agent-Layer" target="_blank" rel="noreferrer">GitHub</a>
                <a href="#" target="_blank" rel="noreferrer">Blog</a>
              </div>
            </div>
          </div>

          <div className="uc-footer-huge">
            <h1 className="uc-huge-text">for ai agents</h1>
          </div>

          <div className="uc-footer-bottom">
            <div className="uc-footer-brand">Agent Layer</div>
            <div className="uc-footer-bottom-links">
              <a href="#about-agent-layer" target="_blank" rel="noreferrer">About Agent Layer</a>
              <a href="#terms" target="_blank" rel="noreferrer">Terms</a>
            </div>
          </div>
        </div>

      </main>
    </div>
  )
}

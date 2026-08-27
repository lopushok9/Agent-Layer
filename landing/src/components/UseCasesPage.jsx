import '../styles/UseCasesPage.css'

const USE_CASES = [
  {
    num: '01',
    name: 'Buy any service',
    description: 'x402 gives your agent the means to expand its own capabilities and reach any paid API or service, with no fees and no subscriptions. Send email, pull fresh and relevant data, and get better research out of the tools a model cannot reach on its own.',
  },
  {
    num: '02',
    name: 'Execute in DeFi',
    description: 'Find opportunities on-chain and act on them. Your agent compares yields, builds strategies of real complexity, and keeps them running long after you have stopped watching.',
  },
  {
    num: '03',
    name: 'Spend anywhere',
    description: 'Crypto is not the limit. Get prepaid and gift cards from the same balance, and pay wherever you need to.',
  },
]

export const UseCasesPage = ({ onInstallClick }) => {
  return (
    <div className="uc-page">

      {/* Header */}
      <header className="uc-header">
        <a href="/" className="uc-brand">
          <img src="/apple-touch-icon.png" alt="AgentLayer logo" className="uc-brand-mark" />
          <span className="wordmark-lockup">
            <span className="uc-brand-text">AgentLayer</span>
            <span className="wordmark-beta" aria-hidden="true">β</span>
          </span>
        </a>

        <nav className="uc-nav">
          <a href="/wallet" className="uc-nav-item">Wallet</a>
          <a href="/connectors" className="uc-nav-item">Connectors</a>
          <a href="/use-cases" className="uc-nav-item uc-nav-active">Use Cases</a>
          <a href="/skill.md" className="uc-nav-item">For LLMs</a>
          <a href="/for-investors" className="uc-nav-item">For Investors</a>
          <a href="/about" className="uc-nav-item">About</a>
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
              From thinking<br />to execution
            </h1>
            <p className="uc-hero-sub">
              AgentLayer turns Claude, OpenClaw or any other agent
              from reasoning about finance into actually executing it.
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
                <a href="/wallet">Wallet</a>
                <a href="/use-cases">Use Cases</a>
                <a href="/skill.md">For LLMs</a>
              </div>
              <div className="uc-link-col">
                <a href="https://docs.agent-layer.tech" target="_blank" rel="noreferrer">Docs</a>
                <a href="https://github.com/lopushok9/Agent-Layer" target="_blank" rel="noreferrer">GitHub</a>
                <a href="https://x.com/agentlayer_ai" target="_blank" rel="noreferrer">Blog</a>
              </div>
            </div>
          </div>

          <div className="uc-footer-huge">
            <h1 className="uc-huge-text">for ai agents</h1>
          </div>

          <div className="uc-footer-bottom">
            <div className="uc-footer-brand">AgentLayer</div>
            <div className="uc-footer-bottom-links">
              <a href="/about">About AgentLayer</a>
              <a href="/terms">Terms</a>
            </div>
            <span className="footer-ca" aria-label="Contract address">
              <span className="footer-ca-label">CA</span>
              <span className="footer-ca-value">444DPguaifQZ5NicFicD9Kni6emKexyq<wbr />qG4dEkUaBAGS</span>
            </span>
          </div>
        </div>

      </main>
    </div>
  )
}

import '../styles/WalletPage.css'

const WALLET_FEATURES = [
  {
    num: '01',
    name: 'Control your keys',
    description: 'Every private key is stored on your own machine, inside the system Keychain. Nobody gets access to them, not even the agent that spends from them.',
  },
  {
    num: '02',
    name: 'Run /wallet',
    description: 'Fast and simple. Run /wallet to see your balance instantly, then turn that context straight into the next action.',
  },
]

export const WalletPage = ({ onInstallClick }) => {
  return (
    <div className="wp-page">
      <header className="wp-header">
        <a href="/" className="wp-brand">
          <img src="/apple-touch-icon.png" alt="AgentLayer logo" className="wp-brand-mark" />
          <span className="wordmark-lockup">
            <span className="wp-brand-text">AgentLayer</span>
            <span className="wordmark-beta" aria-hidden="true">β</span>
          </span>
        </a>

        <nav className="wp-nav">
          <a href="/wallet" className="wp-nav-item wp-nav-active">Wallet</a>
          <a href="/connectors" className="wp-nav-item">Connectors</a>
          <a href="/use-cases" className="wp-nav-item">Use Cases</a>
          <a href="/skill.md" className="wp-nav-item">For LLMs</a>
          <a href="/for-investors" className="wp-nav-item">For Investors</a>
          <a href="/about" className="wp-nav-item">About</a>
        </nav>

        <a href="#" className="wp-btn-cta" onClick={(event) => {
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

      <main className="wp-main">
        <section className="wp-hero">
          <div className="wp-hero-inner">
            <span className="wp-label">Wallet</span>
            <h1 className="wp-hero-headline">
              One wallet,
              <br />every framework
            </h1>
            <p className="wp-hero-sub">
              A universal wallet across all your frameworks.
              Claude Code, OpenClaw, Codex and Hermes are supported out of the box.
            </p>
          </div>
        </section>

        <section className="wp-features">
          {WALLET_FEATURES.map((feature) => (
            <article className="wp-feature" key={feature.num}>
              <div className="wp-feature-inner">
                <span className="wp-feature-num">{feature.num}</span>
                <h2 className="wp-feature-name">{feature.name}</h2>
                <p className="wp-feature-desc">{feature.description}</p>
              </div>
            </article>
          ))}
        </section>

        <div className="wp-footer-section">
          <div className="wp-footer-header">
            <h2 className="wp-footer-title">finance</h2>
            <div className="wp-footer-links">
              <div className="wp-link-col">
                <a href="/wallet">Wallet</a>
                <a href="/use-cases">Use Cases</a>
                <a href="/skill.md">For LLMs</a>
              </div>
              <div className="wp-link-col">
                <a href="https://docs.agent-layer.tech" target="_blank" rel="noreferrer">Docs</a>
                <a href="https://github.com/lopushok9/Agent-Layer/tree/main/agent-wallet" target="_blank" rel="noreferrer">Wallet docs</a>
                <a href="https://github.com/lopushok9/Agent-Layer" target="_blank" rel="noreferrer">GitHub</a>
              </div>
            </div>
          </div>

          <div className="wp-footer-huge">
            <h1 className="wp-huge-text">for ai agents</h1>
          </div>

          <div className="wp-footer-bottom">
            <div className="wp-footer-brand">AgentLayer</div>
            <div className="wp-footer-bottom-links">
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

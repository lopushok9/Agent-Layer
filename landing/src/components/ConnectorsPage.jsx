import '../styles/ConnectorsPage.css'

const USER_STEPS = [
  {
    num: '01',
    title: 'Review before you connect',
    text: 'A connector shows its publisher, endpoint, permissions and tools before it can be enabled. You choose what becomes available to your agent.',
  },
  {
    num: '02',
    title: 'Keep it local',
    text: 'The wallet stores a versioned manifest on your machine. It does not install third-party code, expose your keys, or give a connector permission to sign.',
  },
  {
    num: '03',
    title: 'Use only what you need',
    text: 'Turn a connector on when its data is useful and switch it off when it is not. Its read-only tools appear in your agent after a restart.',
  },
]

export const ConnectorsPage = ({ onInstallClick }) => {
  return (
    <div className="cp-page">
      <header className="cp-header">
        <a href="/" className="cp-brand">
          <img src="/apple-touch-icon.png" alt="AgentLayer logo" className="cp-brand-mark" />
          <span className="wordmark-lockup">
            <span className="cp-brand-text">AgentLayer</span>
            <span className="wordmark-beta" aria-hidden="true">β</span>
          </span>
        </a>

        <nav className="cp-nav" aria-label="Primary navigation">
          <a href="/wallet" className="cp-nav-item">Wallet</a>
          <a href="/connectors" className="cp-nav-item cp-nav-active">Connectors</a>
          <a href="/use-cases" className="cp-nav-item">Use Cases</a>
          <a href="/skill.md" className="cp-nav-item">For LLMs</a>
          <a href="/for-investors" className="cp-nav-item">For Investors</a>
          <a href="/about" className="cp-nav-item">About</a>
        </nav>

        <button type="button" className="cp-btn-cta" onClick={onInstallClick}>
          Install
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true" xmlns="http://www.w3.org/2000/svg">
            <path d="M7 1V9M7 9L4 6M7 9L10 6" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M1 13H13" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </header>

      <main className="cp-main">
        <section className="cp-hero">
          <div className="cp-hero-copy">
            <span className="cp-label"><span className="cp-label-dot" />Connectors · Read-only beta</span>
            <h1 className="cp-hero-title">Give your agent<br />the tools it needs.</h1>
            <p className="cp-hero-lede">
              Add optional crypto, DeFi and agent-service tools to AgentLayer without bloating the wallet for everyone else.
              Every connector stays opt-in, local to your setup and easy to remove.
            </p>
          </div>
          <aside className="cp-hero-aside" aria-label="Connector safety summary">
            <span className="cp-aside-kicker">The boundary</span>
            <p>Read data. Never sign.</p>
            <span>External results stay marked as untrusted data — never as approval to move funds.</span>
          </aside>
        </section>

        <section className="cp-steps" aria-labelledby="cp-steps-title">
          <div className="cp-section-intro">
            <span className="cp-label">For users</span>
            <h2 id="cp-steps-title">Your wallet stays yours.</h2>
          </div>
          <ol className="cp-step-list">
            {USER_STEPS.map((step) => (
              <li className="cp-step" key={step.num}>
                <span className="cp-step-num">{step.num}</span>
                <div>
                  <h3>{step.title}</h3>
                  <p>{step.text}</p>
                </div>
              </li>
            ))}
          </ol>
        </section>

        <section className="cp-install" aria-labelledby="cp-install-title">
          <div className="cp-install-copy">
            <span className="cp-label">Three commands</span>
            <h2 id="cp-install-title">Inspect. Enable. Use.</h2>
            <p>A connector is never silently enabled. Review its manifest first, then make the choice explicit.</p>
          </div>
          <pre className="cp-code"><code>{`wallet connectors inspect ./connector.json
wallet connectors install ./connector.json --enable --yes
wallet connectors tools`}</code></pre>
        </section>

        <section className="cp-developers" aria-labelledby="cp-developers-title">
          <div className="cp-developer-title">
            <span className="cp-label">For developers</span>
            <h2 id="cp-developers-title">Build once.<br />Connect everywhere.</h2>
          </div>
          <div className="cp-developer-copy">
            <p>
              Host a public HTTPS read endpoint, describe it with a versioned manifest and define strict input/output schemas.
              Users opt in through the same wallet CLI; OpenClaw, Codex, Claude Code and Hermes discover the enabled tools automatically.
            </p>
            <div className="cp-developer-notes">
              <span>Public endpoint</span>
              <span>Versioned manifest</span>
              <span>Schema-checked results</span>
            </div>
            <p className="cp-coming-soon">Detailed developer docs are coming next.</p>
          </div>
        </section>

        <footer className="cp-footer">
          <div className="cp-footer-top">
            <h2>finance</h2>
            <div className="cp-footer-links">
              <a href="/wallet">Wallet</a>
              <a href="/connectors">Connectors</a>
              <a href="https://github.com/lopushok9/Agent-Layer" target="_blank" rel="noreferrer">GitHub</a>
            </div>
          </div>
          <h3>for ai agents</h3>
          <div className="cp-footer-bottom">
            <span>AgentLayer</span>
            <div><a href="/about">About AgentLayer</a><a href="/terms">Terms</a></div>
          </div>
        </footer>
      </main>
    </div>
  )
}

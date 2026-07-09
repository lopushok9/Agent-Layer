import '../styles/ForInvestorsPage.css'

export const ForInvestorsPage = ({ onInstallClick }) => {
  return (
    <div className="fi-page">
      <header className="fi-header">
        <a href="/" className="fi-brand">
          <img src="/apple-touch-icon.png" alt="AgentLayer logo" className="fi-brand-mark" />
          <span className="wordmark-lockup">
            <span className="fi-brand-text">AgentLayer</span>
            <span className="wordmark-beta" aria-hidden="true">β</span>
          </span>
        </a>

        <nav className="fi-nav">
          <a href="/wallet" className="fi-nav-item">Wallet</a>
          <a href="/mcp" className="fi-nav-item">MCP</a>
          <a href="/use-cases" className="fi-nav-item">Use Cases</a>
          <a href="/how-to-use" className="fi-nav-item">How to use</a>
          <a href="/skill.md" className="fi-nav-item">For LLMs</a>
          <a href="/for-investors" className="fi-nav-item fi-nav-active">For Investors</a>
          <a href="/about" className="fi-nav-item">About</a>
        </nav>

        <a href="#" className="fi-btn-cta" onClick={(event) => {
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

      <main className="fi-main">
        <section className="fi-slide fi-slide-hero">
          <div className="fi-shell" />
          <div className="fi-slide-content">
            <div className="fi-topbar">
              <div className="fi-mini-brand">AgentLayer <span className="fi-beta-mini">β</span></div>
              <div>Investor overview</div>
            </div>

            <div className="fi-hero-grid">
              <div>
                <div className="fi-kicker">Personal finance agent for the crypto era</div>
                <h1 className="fi-hero-title">Turn AI into financial action.</h1>
                <p className="fi-lede">
                  AgentLayer is a hybrid consumer + infrastructure product: an AI-native finance layer that helps users analyze opportunities,
                  prepare onchain actions, and execute safely without handing agents direct control over keys or funds.
                </p>
              </div>

              <aside className="fi-panel">
                <div className="fi-panel-label">Core thesis</div>
                <div className="fi-panel-big">The next retail financial interface is agentic — but trust and execution have to be rebuilt from first principles.</div>
              </aside>
            </div>

            <div className="fi-footerline">
              <div>agent-layer.tech</div>
              <div>01 / 05</div>
            </div>
          </div>
        </section>

        <section className="fi-slide">
          <div className="fi-shell" />
          <div className="fi-slide-content">
            <div className="fi-topbar">
              <div className="fi-mini-brand">AgentLayer <span className="fi-beta-mini">β</span></div>
              <div>Business model</div>
            </div>

            <div className="fi-section-header">
              <h2 className="fi-section-title">Revenue comes from swaps and DeFi activity.</h2>
              <div className="fi-section-note">A proven model already used by major wallet leaders.</div>
            </div>

            <div className="fi-text-columns">
              <div className="fi-text-block">
                <div className="fi-kicker">Core revenue stream</div>
                <div className="fi-big-text">AgentLayer earns commissions on swaps, yield routing, and other DeFi actions executed through the product.</div>
                <div className="fi-big-text">Revenue scales with real user activity, not passive installs.</div>
              </div>

              <div className="fi-text-block">
                <div className="fi-kicker">Why this works</div>
                <div className="fi-big-text">This commission-based model is time-tested and already drives tens of millions of dollars for category leaders like Phantom.</div>
                <div className="fi-big-text">In beta, commissions are intentionally turned off to reduce friction and maximize early product learning.</div>
              </div>
            </div>

            <div className="fi-footerline">
              <div>Commissions on real financial activity.</div>
              <div>02 / 05</div>
            </div>
          </div>
        </section>

        <section className="fi-slide">
          <div className="fi-shell" />
          <div className="fi-slide-content">
            <div className="fi-topbar">
              <div className="fi-mini-brand">AgentLayer <span className="fi-beta-mini">β</span></div>
              <div>Why now</div>
            </div>

            <div className="fi-text-columns fi-why-columns">
              <div className="fi-text-block">
                <div className="fi-kicker">The missing layer</div>
                <div className="fi-quote">AI can recommend. Wallets can execute. The bridge between the two is still broken.</div>
                <p className="fi-lede fi-lede-wide">
                  Retail users still have to translate intention into action themselves — across protocols, rates, routes, wallets, and security.
                  Giving an agent full signing power is unacceptable. Without execution context, the agent is far less useful.
                </p>
              </div>

              <div className="fi-text-block">
                <div className="fi-kicker">Why timing matters</div>
                <div className="fi-big-text">AI-native behavior is becoming the default interface layer for complex consumer workflows.</div>
                <div className="fi-big-text">Too many fragmented tools still sit between market analysis and actual execution.</div>
                <div className="fi-big-text">The winner is likely the product that makes agentic finance feel safe, legible, and useful first.</div>
              </div>
            </div>

            <div className="fi-footerline">
              <div>Advice alone is not a product. Execution alone is not trust.</div>
              <div>03 / 05</div>
            </div>
          </div>
        </section>

        <section className="fi-slide">
          <div className="fi-shell" />
          <div className="fi-slide-content">
            <div className="fi-topbar">
              <div className="fi-mini-brand">AgentLayer <span className="fi-beta-mini">β</span></div>
              <div>Why we win</div>
            </div>

            <div className="fi-section-header">
              <h2 className="fi-section-title">A consumer wedge built on real agent finance infrastructure.</h2>
              <div className="fi-section-note">Fast to install, permissionless by design, and built for broad agent access.</div>
            </div>

            <div className="fi-text-columns">
              <div className="fi-text-block">
                <div className="fi-kicker">Permissionless wallet</div>
                <div className="fi-big-text">No signup, no API keys, and far less friction than flows built around tools like Coinbase Wallet SDK or Bankr.</div>
                <div className="fi-big-text">An agent can install and prepare the stack itself — the user can simply ask for it.</div>
              </div>

              <div className="fi-text-block">
                <div className="fi-kicker">Why this matters</div>
                <div className="fi-big-text">AgentLayer supports popular networks instead of concentrating around a single chain, widening the surface for real financial activity.</div>
                <div className="fi-big-text">Built around OpenClaw from the ground up, the agent workflow feels native rather than bolted on.</div>
              </div>
            </div>

            <div className="fi-footerline">
              <div>Product on top. Infra underneath.</div>
              <div>04 / 05</div>
            </div>
          </div>
        </section>

        <section className="fi-slide fi-slide-closing">
          <div className="fi-shell" />
          <div className="fi-slide-content">
            <div className="fi-topbar">
              <div className="fi-mini-brand">AgentLayer <span className="fi-beta-mini">β</span></div>
              <div>Early proof</div>
            </div>

            <div className="fi-section-header fi-section-header-single">
              <h2 className="fi-section-title">Already live as a beta, with the stack assembled today.</h2>
            </div>

            <div className="fi-closing-message">
              Crypto first, but not limited to crypto. Get access to RWAs and tokenized assets — including stocks, gold, and oil. Build complex autonomous strategies for your agent, or trade alongside it.
            </div>

            <div className="fi-closing-cta">
              <div className="fi-kicker">Ask your agent to install</div>
              <a className="fi-closing-link" href="https://github.com/lopushok9/Agent-Layer.git" target="_blank" rel="noreferrer">https://github.com/lopushok9/Agent-Layer.git</a>
            </div>

            <div className="fi-footerline">
              <div>Early, but materially built.</div>
              <div>05 / 05</div>
            </div>
          </div>
        </section>
      </main>
    </div>
  )
}

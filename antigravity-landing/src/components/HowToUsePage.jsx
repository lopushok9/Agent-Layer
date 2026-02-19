import '../styles/HowToUsePage.css'

export const HowToUsePage = () => {
  return (
    <div className="htu-page">

      {/* Header */}
      <header className="htu-header">
        <a href="#" className="htu-brand">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
            <path d="M12 2L2 7L12 12L22 7L12 2Z" fill="#111213" />
            <path d="M2 17L12 22L22 17" stroke="#111213" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M2 12L12 17L22 12" stroke="#111213" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <span className="htu-brand-text">AgentLayer</span>
        </a>

        <nav className="htu-nav">
          <a href="#product" className="htu-nav-item">Product</a>
          <a href="#use-cases" className="htu-nav-item">Use Cases</a>
          <a href="#how-to-use" className="htu-nav-item htu-nav-active">How to use</a>
          <a href="#" className="htu-nav-item">Resources</a>
        </nav>

        <a href="#" className="htu-btn-cta">Download</a>
      </header>

      <main className="htu-main">

        {/* Hero */}
        <section className="htu-hero">
          <div className="htu-hero-inner">
            <span className="htu-label">How to use</span>
            <h1 className="htu-hero-headline">
              Connect once.<br />The agent handles the rest.
            </h1>
            <p className="htu-hero-sub">
              Paste one config block and your agent gains access to
              16 financial tools — prices, DeFi yields, on-chain data,
              gas, and agent identity. No code. No setup. No docs to read.
            </p>
          </div>
        </section>

        {/* Step 01 — OpenClaw */}
        <section className="htu-step htu-step-primary">
          <div className="htu-step-inner">
            <span className="htu-step-num">01</span>
            <div className="htu-step-content">
              <h2 className="htu-step-name">OpenClaw</h2>
              <p className="htu-step-desc">
                Add this block to your OpenClaw MCP config. The agent will
                automatically discover all 16 tools and understand how to use
                them — no instructions needed.
              </p>
              <div className="htu-code-block">
                <div className="htu-code-header">
                  <span className="htu-code-label">claude_desktop_config.json</span>
                  <span className="htu-code-dot" />
                </div>
                <pre className="htu-code">{`{
  "mcpServers": {
    "AgentLayer": {
      "url": "https://agent-layer-production-852f.up.railway.app/mcp"
    }
  }
}`}</pre>
              </div>
              <p className="htu-beta-note">
                Beta version — shared public instance.{' '}
                <a href="https://github.com" className="htu-link">Deploy your own</a>{' '}
                for dedicated capacity.
              </p>
            </div>
          </div>
        </section>

        {/* Step 02 — Other environments */}
        <section className="htu-step">
          <div className="htu-step-inner">
            <span className="htu-step-num">02</span>
            <div className="htu-step-content">
              <h2 className="htu-step-name">Other environments</h2>
              <p className="htu-step-desc">
                AgentLayer works with any MCP-compatible client.
                The same URL, the same tools, the same zero-config experience.
              </p>
              <div className="htu-env-grid">
                <div className="htu-env">
                  <span className="htu-env-name">Cursor</span>
                  <span className="htu-env-desc">Add to MCP settings → paste URL</span>
                </div>
                <div className="htu-env">
                  <span className="htu-env-name">Windsurf</span>
                  <span className="htu-env-desc">MCP Servers → New → paste URL</span>
                </div>
                <div className="htu-env">
                  <span className="htu-env-name">Claude Code</span>
                  <span className="htu-env-desc">Add to .claude.json mcpServers</span>
                </div>
                <div className="htu-env">
                  <span className="htu-env-name">Any MCP client</span>
                  <span className="htu-env-desc">Standard HTTP transport, SSE streaming</span>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* Footer */}
        <div className="htu-footer-section">
          <div className="htu-footer-header">
            <h2 className="htu-footer-title">finance</h2>
            <div className="htu-footer-links">
              <div className="htu-link-col">
                <a href="#">Download</a>
                <a href="#product">Product</a>
                <a href="#">Docs</a>
                <a href="#">Changelog</a>
                <a href="#">Press</a>
                <a href="#">Releases</a>
              </div>
              <div className="htu-link-col">
                <a href="#">Blog</a>
                <a href="#how-to-use">How to use</a>
                <a href="#use-cases">Use Cases</a>
              </div>
            </div>
          </div>

          <div className="htu-footer-huge">
            <h1 className="htu-huge-text">for ai agents</h1>
          </div>

          <div className="htu-footer-bottom">
            <div className="htu-footer-brand">Agent Layer</div>
            <div className="htu-footer-bottom-links">
              <a href="#">About Agent Layer</a>
              <a href="#">Terms</a>
            </div>
          </div>
        </div>

      </main>
    </div>
  )
}

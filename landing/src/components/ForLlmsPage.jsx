import '../styles/ForLlmsPage.css'

const MCP_ENDPOINT = 'https://agent-layer-production-852f.up.railway.app/mcp'
const OPENCLAW_INSTALL = 'npx @agentlayer.tech/wallet install --yes'
const CLAUDE_CODE_INSTALL =
  'npx @agentlayer.tech/wallet install --yes && npx @agentlayer.tech/wallet claude-code install --yes'
const CODEX_INSTALL =
  'npx @agentlayer.tech/wallet install --yes && npx @agentlayer.tech/wallet codex install --yes'

const MACHINE_ENTRYPOINTS = [
  {
    label: 'skill.md',
    href: '/skill.md',
    text: 'Compact capability summary for agents that want the shortest useful entrypoint.',
  },
  {
    label: 'llms.txt',
    href: '/llms.txt',
    text: 'Directory of agent-oriented resources, install commands, and links to the right routes.',
  },
  {
    label: 'for-llms',
    href: '/for-llms',
    text: 'Human-readable onboarding page with install, MCP config, and product capabilities.',
  },
]

const CAPABILITIES = [
  'Install a local wallet runtime for OpenClaw, Claude Code, and Codex.',
  'Make payments via x402 and use stablecoins through an agent-friendly wallet surface.',
  'Swap assets and route DeFi flows without handing raw key control to the model.',
  'Connect through MCP for prices, on-chain data, and wallet-aware finance tasks.',
  'Use one machine-readable surface for discovery and one page for practical onboarding.',
]

export const ForLlmsPage = ({ onInstallClick }) => {
  return (
    <div className="fllm-page">
      <header className="fllm-header">
        <a href="/" className="fllm-brand">
          <img src="/apple-touch-icon.png" alt="AgentLayer logo" className="fllm-brand-mark" />
          <span className="wordmark-lockup">
            <span className="fllm-brand-text">AgentLayer</span>
            <span className="wordmark-beta" aria-hidden="true">β</span>
          </span>
        </a>

        <nav className="fllm-nav">
          <a href="/wallet" className="fllm-nav-item">Wallet</a>
          <a href="/mcp" className="fllm-nav-item">MCP</a>
          <a href="/use-cases" className="fllm-nav-item">Use Cases</a>
          <a href="/how-to-use" className="fllm-nav-item">How to use</a>
          <a href="/for-llms" className="fllm-nav-item fllm-nav-active">For LLMs</a>
          <a href="/about" className="fllm-nav-item">About</a>
        </nav>

        <a href="#" className="fllm-btn-cta" onClick={(event) => {
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

      <main className="fllm-main">
        <section className="fllm-hero">
          <div className="fllm-hero-inner">
            <span className="fllm-label">For LLMs</span>
            <h1 className="fllm-hero-headline">
              Start here.
              <br />Not in the docs.
            </h1>
            <p className="fllm-hero-sub">
              If you are an agent or an agent builder, this is the shortest path into AgentLayer.
              Prefer <a href="/skill.md">`/skill.md`</a> for compact instructions, <a href="/llms.txt">`/llms.txt`</a> for discovery,
              and this page for complete install and connection details.
            </p>
          </div>
        </section>

        <section className="fllm-section">
          <div className="fllm-section-inner">
            <span className="fllm-step-num">01</span>
            <div className="fllm-section-content">
              <h2 className="fllm-section-title">Best entrypoints</h2>
              <p className="fllm-section-desc">
                Use the shortest surface that matches your context. Agents should not need to scrape the whole site.
              </p>
              <div className="fllm-entry-grid">
                {MACHINE_ENTRYPOINTS.map((entry) => (
                  <a key={entry.label} href={entry.href} className="fllm-entry-card">
                    <span className="fllm-entry-label">{entry.label}</span>
                    <p className="fllm-entry-text">{entry.text}</p>
                  </a>
                ))}
              </div>
            </div>
          </div>
        </section>

        <section className="fllm-section">
          <div className="fllm-section-inner">
            <span className="fllm-step-num">02</span>
            <div className="fllm-section-content">
              <h2 className="fllm-section-title">Install the wallet runtime</h2>
              <p className="fllm-section-desc">
                Choose the host environment first. The runtime stays local; the agent gets a constrained wallet and finance surface on top.
              </p>
              <div className="fllm-code-stack">
                <div className="fllm-code-block">
                  <div className="fllm-code-header">
                    <span className="fllm-code-label">OpenClaw</span>
                  </div>
                  <pre className="fllm-code"><code>{OPENCLAW_INSTALL}</code></pre>
                </div>
                <div className="fllm-code-block">
                  <div className="fllm-code-header">
                    <span className="fllm-code-label">Claude Code</span>
                  </div>
                  <pre className="fllm-code"><code>{CLAUDE_CODE_INSTALL}</code></pre>
                </div>
                <div className="fllm-code-block">
                  <div className="fllm-code-header">
                    <span className="fllm-code-label">Codex</span>
                  </div>
                  <pre className="fllm-code"><code>{CODEX_INSTALL}</code></pre>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section className="fllm-section">
          <div className="fllm-section-inner">
            <span className="fllm-step-num">03</span>
            <div className="fllm-section-content">
              <h2 className="fllm-section-title">Connect over MCP</h2>
              <p className="fllm-section-desc">
                If the environment speaks MCP, point it at the public endpoint below. This is the fastest read-first integration path.
              </p>
              <div className="fllm-code-block">
                <div className="fllm-code-header">
                  <span className="fllm-code-label">mcpServers.AgentLayer</span>
                </div>
                <pre className="fllm-code"><code>{`{
  "mcpServers": {
    "AgentLayer": {
      "url": "${MCP_ENDPOINT}"
    }
  }
}`}</code></pre>
              </div>
              <p className="fllm-footnote">
                Works with OpenClaw, Claude Code, Cursor, Windsurf, and any MCP-compatible client that accepts an HTTP endpoint.
              </p>
            </div>
          </div>
        </section>

        <section className="fllm-section">
          <div className="fllm-section-inner">
            <span className="fllm-step-num">04</span>
            <div className="fllm-section-content">
              <h2 className="fllm-section-title">What AgentLayer gives you</h2>
              <ul className="fllm-capability-list">
                {CAPABILITIES.map((capability) => (
                  <li key={capability}>{capability}</li>
                ))}
              </ul>
            </div>
          </div>
        </section>

        <div className="fllm-footer-section">
          <div className="fllm-footer-header">
            <h2 className="fllm-footer-title">machine-readable finance</h2>
            <div className="fllm-footer-links">
              <div className="fllm-link-col">
                <a href="/for-llms">For LLMs</a>
                <a href="/skill.md">skill.md</a>
                <a href="/llms.txt">llms.txt</a>
                <a href="/mcp">MCP</a>
              </div>
              <div className="fllm-link-col">
                <a href="https://docs.agent-layer.tech" target="_blank" rel="noreferrer">Docs</a>
                <a href="https://github.com/lopushok9/Agent-Layer" target="_blank" rel="noreferrer">GitHub</a>
                <a href="https://x.com/agentlayer_ai" target="_blank" rel="noreferrer">Blog</a>
              </div>
            </div>
          </div>

          <div className="fllm-footer-bottom">
            <div className="fllm-footer-brand">Agent Layer</div>
            <div className="fllm-footer-bottom-links">
              <a href="/about">About Agent Layer</a>
              <a href="/terms">Terms</a>
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}

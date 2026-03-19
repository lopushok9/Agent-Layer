import '../styles/WalletPage.css'

const WALLET_FEATURES = [
  {
    num: '01',
    name: 'Wallet context',
    description: 'Expose wallet address, balances, portfolio state, token prices and staking context through a compact OpenClaw tool surface. The agent reads first before it acts.',
    tools: ['get_wallet_address', 'get_wallet_balance', 'get_wallet_portfolio', 'get_solana_token_prices'],
  },
  {
    num: '02',
    name: 'Safe execution',
    description: 'Transfers, swaps, staking, stake deactivation and withdrawals follow a preview-first path. Prepare returns an execution plan only, while execute is reserved for explicitly approved actions.',
    tools: ['transfer_sol', 'transfer_spl_token', 'swap_solana_tokens', 'stake_sol_native'],
  },
  {
    num: '03',
    name: 'Approval control',
    description: 'Sensitive actions are bound to host-issued approval tokens. Mainnet flows require explicit confirmation, and execution remains tied to the approved wallet intent instead of free-form agent output.',
    tools: ['approval_token', 'mainnet_confirmation', 'single-use approval', 'preview → execute'],
  },
  {
    num: '04',
    name: 'Encrypted storage',
    description: 'Per-user wallets are encrypted at rest, derived from sealed runtime secrets, and isolated by user and network. Secret material stays out of config JSON and out of plain runtime env.',
    tools: ['sealed_keys.json', 'AGENT_WALLET_BOOT_KEY', 'per-user encryption', 'network isolation'],
  },
  {
    num: '05',
    name: 'Mainnet hardening',
    description: 'Mainnet wallets are pinned by address, legacy plaintext wallets can be migrated, and runtime policy rejects unsafe secret-loading paths. The goal is operational safety, not just happy-path demos.',
    tools: ['wallet pinning', 'plaintext migration', 'runtime secret rejection', 'sign-only support'],
  },
]

export const WalletPage = ({ onInstallClick }) => {
  return (
    <div className="wp-page">
      <header className="wp-header">
        <a href="#" className="wp-brand">
          <img src="/apple-touch-icon.png" alt="AgentLayer logo" className="wp-brand-mark" />
          <span className="wordmark-lockup">
            <span className="wp-brand-text">AgentLayer</span>
            <span className="wordmark-beta" aria-hidden="true">β</span>
          </span>
        </a>

        <nav className="wp-nav">
          <a href="#wallet" className="wp-nav-item wp-nav-active">Wallet</a>
          <a href="#mcp" className="wp-nav-item">MCP</a>
          <a href="#use-cases" className="wp-nav-item">Use Cases</a>
          <a href="#how-to-use" className="wp-nav-item">How to use</a>
          <a href="#about-agent-layer" className="wp-nav-item">About</a>
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
              A local wallet runtime
              <br />for OpenClaw agents
            </h1>
            <p className="wp-hero-sub">
              AgentLayer Wallet gives OpenClaw a hardened execution layer for Solana.
            </p>
            <div className="wp-status">
              <span className="wp-status-dot" />
              beta. local runtime for balances, swaps and staking
            </div>
          </div>
        </section>

        <section className="wp-features">
          {WALLET_FEATURES.map((feature) => (
            <article className="wp-feature" key={feature.num}>
              <div className="wp-feature-inner">
                <span className="wp-feature-num">{feature.num}</span>
                <h2 className="wp-feature-name">{feature.name}</h2>
                <p className="wp-feature-desc">{feature.description}</p>
                <div className="wp-feature-tags">
                  {feature.tools.map((tool) => (
                    <span className="wp-tag" key={tool}>{tool}</span>
                  ))}
                </div>
              </div>
            </article>
          ))}
        </section>

        <div className="wp-footer-section">
          <div className="wp-footer-header">
            <h2 className="wp-footer-title">finance</h2>
            <div className="wp-footer-links">
              <div className="wp-link-col">
                <a href="#wallet">Wallet</a>
                <a href="#mcp">MCP</a>
                <a href="#use-cases">Use Cases</a>
                <a href="#how-to-use">How to use</a>
              </div>
              <div className="wp-link-col">
                <a href="https://github.com/lopushok9/Agent-Layer/tree/main/agent-wallet" target="_blank" rel="noreferrer">Wallet docs</a>
                <a href="https://github.com/lopushok9/Agent-Layer" target="_blank" rel="noreferrer">GitHub</a>
              </div>
            </div>
          </div>

          <div className="wp-footer-huge">
            <h1 className="wp-huge-text">for ai agents</h1>
          </div>

          <div className="wp-footer-bottom">
            <div className="wp-footer-brand">Agent Layer</div>
            <div className="wp-footer-bottom-links">
              <span className="footer-ca" aria-label="Contract address">
                <span className="footer-ca-label">CA:</span>
                <span className="footer-ca-value">444DPguaifQZ5NicFicD9Kni6emKexyq<wbr />qG4dEkUaBAGS</span>
              </span>
              <a href="#about-agent-layer">About Agent Layer</a>
              <a href="#terms">Terms</a>
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}

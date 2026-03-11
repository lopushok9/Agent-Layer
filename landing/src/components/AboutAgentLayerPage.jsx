import '../styles/AboutAgentLayerPage.css'

const PILLARS = [
  {
    num: '01',
    title: 'Agent-native by design',
    text: 'AgentLayer was built for machine-to-machine workflows first. Every tool returns predictable JSON with stable keys, so agents can plan, compare and execute without fragile parsers.',
  },
  {
    num: '02',
    title: 'Reliability over novelty',
    text: 'The stack is engineered around continuity. Price data follows a fallback chain, responses are cached with sensible TTLs, and provider outages degrade gracefully instead of breaking flows.',
  },
  {
    num: '03',
    title: 'Open financial coverage',
    text: 'From market structure to on-chain execution context, the goal is broad and practical coverage: pricing, DeFi metrics, wallet state, gas conditions, and identity for autonomous agents.',
  },
]

export const AboutAgentLayerPage = ({ onInstallClick }) => {
  return (
    <div className="ab-page">
      <header className="ab-header">
        <a href="#" className="ab-brand" target="_blank" rel="noreferrer">
          <img src="/apple-touch-icon.png" alt="AgentLayer logo" className="ab-brand-mark" />
          <span className="ab-brand-text">AgentLayer</span>
        </a>

        <nav className="ab-nav">
          <a href="#product" className="ab-nav-item" target="_blank" rel="noreferrer">Product</a>
          <a href="#use-cases" className="ab-nav-item" target="_blank" rel="noreferrer">Use Cases</a>
          <a href="#how-to-use" className="ab-nav-item" target="_blank" rel="noreferrer">How to use</a>
          <a href="#about-agent-layer" className="ab-nav-item ab-nav-active" target="_blank" rel="noreferrer">About</a>
        </nav>

        <a href="#" className="ab-btn-cta" onClick={(event) => {
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

      <main className="ab-main">
        <section className="ab-hero">
          <div className="ab-hero-inner">
            <span className="ab-label">About Agent Layer</span>
            <h1 className="ab-hero-headline">
              The finance layer
              <br />for autonomous agents
            </h1>
            <p className="ab-hero-sub">
              AgentLayer connects AI systems to real financial context without forcing every team
              to build infra from scratch. One protocol endpoint, structured tools, and production
              behavior from day one.
            </p>
          </div>
        </section>

        <section className="ab-pillars">
          {PILLARS.map((pillar) => (
            <article className="ab-pillar" key={pillar.num}>
              <div className="ab-pillar-inner">
                <span className="ab-pillar-num">{pillar.num}</span>
                <h2 className="ab-pillar-title">{pillar.title}</h2>
                <p className="ab-pillar-text">{pillar.text}</p>
              </div>
            </article>
          ))}
        </section>

        <div className="ab-footer-section">
          <div className="ab-footer-header">
            <h2 className="ab-footer-title">finance</h2>
            <div className="ab-footer-links">
              <div className="ab-link-col">
                <a href="#product" target="_blank" rel="noreferrer">Product</a>
                <a href="#use-cases" target="_blank" rel="noreferrer">Use Cases</a>
                <a href="#how-to-use" target="_blank" rel="noreferrer">How to use</a>
              </div>
              <div className="ab-link-col">
                <a href="https://github.com/lopushok9/Agent-Layer" target="_blank" rel="noreferrer">GitHub</a>
                <a href="#" target="_blank" rel="noreferrer">Blog</a>
              </div>
            </div>
          </div>

          <div className="ab-footer-huge">
            <h1 className="ab-huge-text">for ai agents</h1>
          </div>

          <div className="ab-footer-bottom">
            <div className="ab-footer-brand">Agent Layer</div>
            <div className="ab-footer-bottom-links">
              <a href="#about-agent-layer" className="ab-footer-active-link" target="_blank" rel="noreferrer">About Agent Layer</a>
              <a href="#terms" target="_blank" rel="noreferrer">Terms</a>
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}

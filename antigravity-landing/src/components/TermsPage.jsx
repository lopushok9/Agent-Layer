import '../styles/TermsPage.css'

const SECTIONS = [
  {
    num: '01',
    title: 'Informational Use Only',
    text: 'All content, metrics, and outputs provided through AgentLayer are for informational and technical integration purposes only.',
  },
  {
    num: '02',
    title: 'Not Financial Advice',
    text: 'Nothing on this site or in the API responses constitutes financial, investment, legal, or tax advice. Any decisions remain solely your responsibility.',
  },
  {
    num: '03',
    title: 'DYOR / NFA',
    text: 'Always do your own research before acting on any data. NFA: not financial advice.',
  },
  {
    num: '04',
    title: 'Data and Availability',
    text: 'Data is sourced from third-party providers and may be delayed, incomplete, or unavailable. We do not guarantee uninterrupted service or absolute accuracy.',
  },
]

export const TermsPage = () => {
  return (
    <div className="tm-page">
      <header className="tm-header">
        <a href="#" className="tm-brand">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
            <path d="M12 2L2 7L12 12L22 7L12 2Z" fill="#111213" />
            <path d="M2 17L12 22L22 17" stroke="#111213" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M2 12L12 17L22 12" stroke="#111213" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <span className="tm-brand-text">AgentLayer</span>
        </a>

        <nav className="tm-nav">
          <a href="#product" className="tm-nav-item">Product</a>
          <a href="#use-cases" className="tm-nav-item">Use Cases</a>
          <a href="#how-to-use" className="tm-nav-item">How to use</a>
          <a href="#about-agent-layer" className="tm-nav-item">About</a>
        </nav>

        <a href="#" className="tm-btn-cta">Download</a>
      </header>

      <main className="tm-main">
        <section className="tm-hero">
          <div className="tm-hero-inner">
            <span className="tm-label">Terms</span>
            <h1 className="tm-hero-headline">
              Terms and
              <br />Risk Disclosure
            </h1>
            <p className="tm-hero-sub">
              Please review these terms before using AgentLayer. By using the website or MCP endpoint,
              you acknowledge and agree to the statements below.
            </p>
          </div>
        </section>

        <section className="tm-sections">
          {SECTIONS.map((section) => (
            <article className="tm-section" key={section.num}>
              <div className="tm-section-inner">
                <span className="tm-section-num">{section.num}</span>
                <h2 className="tm-section-title">{section.title}</h2>
                <p className="tm-section-text">{section.text}</p>
              </div>
            </article>
          ))}
        </section>

        <div className="tm-footer-section">
          <div className="tm-footer-header">
            <h2 className="tm-footer-title">finance</h2>
            <div className="tm-footer-links">
              <div className="tm-link-col">
                <a href="#">Download</a>
                <a href="#product">Product</a>
                <a href="#">Docs</a>
                <a href="#">Changelog</a>
                <a href="#">Press</a>
                <a href="#">Releases</a>
              </div>
              <div className="tm-link-col">
                <a href="#">Blog</a>
                <a href="#how-to-use">How to use</a>
                <a href="#use-cases">Use Cases</a>
              </div>
            </div>
          </div>

          <div className="tm-footer-huge">
            <h1 className="tm-huge-text">for ai agents</h1>
          </div>

          <div className="tm-footer-bottom">
            <div className="tm-footer-brand">Agent Layer</div>
            <div className="tm-footer-bottom-links">
              <a href="#about-agent-layer">About Agent Layer</a>
              <a href="#terms" className="tm-footer-active-link">Terms</a>
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}

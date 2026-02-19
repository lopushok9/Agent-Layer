import React, { useState } from 'react'
import '../styles/Interface.css' // We'll create this

export const Interface = () => {
    const [mobileMenuOpen, setMobileMenuOpen] = useState(false)

    return (
        <div className="interface">
            <header className="header">
                <div className="brand-block">
                    {/* Brand Icon */}
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <path d="M12 2L2 7L12 12L22 7L12 2Z" fill="#111213" />
                        <path d="M2 17L12 22L22 17" stroke="#111213" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                        <path d="M2 12L12 17L22 12" stroke="#111213" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                    <span className="brand-text">AgentLayer</span>
                </div>

                <nav className="nav desktop-only">
                    <a href="#product" className="nav-item">Product</a>
                    <a href="#use-cases" className="nav-item">Use Cases</a>
                    <a href="#how-to-use" className="nav-item">How to use</a>
                    <a href="#" className="nav-item">Resources</a>
                </nav>

                <button className="btn-download desktop-only">
                    Download
                    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <path d="M7 1V9M7 9L4 6M7 9L10 6" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                        <path d="M1 13H13" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                </button>

                {/* Mobile Menu Trigger */}
                <button className="mobile-menu-btn" onClick={() => setMobileMenuOpen(true)} aria-label="Open menu">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <path d="M3 12H21" stroke="#111213" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                        <path d="M3 6H21" stroke="#111213" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                        <path d="M3 18H21" stroke="#111213" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                </button>
            </header>

            {/* Mobile Menu Overlay */}
            <div className={`mobile-menu-overlay ${mobileMenuOpen ? 'open' : ''}`}>
                <div className="mobile-menu-header">
                    <div className="brand-block-menu">
                        <svg className="google-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                            <path d="M12 2L2 7L12 12L22 7L12 2Z" fill="#111213" />
                            <path d="M2 17L12 22L22 17" stroke="#111213" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                            <path d="M2 12L12 17L22 12" stroke="#111213" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                        <span className="brand-text-menu">AgentLayer</span>
                        <span className="brand-subtext-menu">Antigravity</span>
                    </div>
                    <button className="mobile-menu-close" onClick={() => setMobileMenuOpen(false)} aria-label="Close menu">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                            <path d="M18 6L6 18" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
                            <path d="M6 6L18 18" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                    </button>
                </div>

                <div className="mobile-menu-content">
                    <nav className="mobile-nav-list">
                        <a href="#product" className="mobile-nav-link">Product</a>
                        <a href="#use-cases" className="mobile-nav-link">Use Cases</a>
                        <a href="#how-to-use" className="mobile-nav-link">How to use</a>
                        <a href="#" className="mobile-nav-link">Resources</a>
                    </nav>
                </div>
            </div>

            <main className="hero">
                <div className="hero-content">
                    <div className="hero-logo-row">
                        <svg width="32" height="32" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
                            <rect width="32" height="32" rx="8" fill="#111213" />
                            <path d="M16 6L6 11L16 16L26 11L16 6Z" fill="white" />
                            <path d="M6 21L16 26L26 21" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                            <path d="M6 16L16 21L26 16" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                        <span className="hero-brand-text">AgentLayer</span>
                    </div>

                    <h1 className="hero-headline">You have successfully authenticated.</h1>

                    <p className="subtitle">
                        You should be redirected back to the product. <a href="#">Click here</a> if not working.
                    </p>

                    <div className="hero-footer-links">
                        <a href="#">Docs</a>
                        <span className="separator"></span>
                        <a href="#">Twitter</a>
                    </div>
                </div>
            </main>

            {/* Continuation Section (Reference Implementation) */}
            <div className="extended-section">
                <div className="extended-header">
                    <h2 className="finance-title">finance</h2>
                    <div className="extended-links">
                        <div className="link-column">
                            <a href="#">Download</a>
                            <a href="#">Product</a>
                            <a href="#">Docs</a>
                            <a href="#">Changelog</a>
                            <a href="#">Press</a>
                            <a href="#">Releases</a>
                        </div>
                        <div className="link-column">
                            <a href="#">Blog</a>
                            <a href="#">Pricing</a>
                            <a href="#">Use Cases</a>
                        </div>
                    </div>
                </div>

                <div className="huge-text-container">
                    <h1 className="huge-antigravity">for ai agents</h1>
                </div>

                <div className="extended-footer">
                    <div className="footer-brand">Agent Layer</div>
                    <div className="footer-bottom-links">
                        <a href="#about-agent-layer">About Agent Layer</a>
                        <a href="#terms">Terms</a>
                    </div>
                </div>
            </div>

        </div >
    )
}

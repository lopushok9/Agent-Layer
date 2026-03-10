import React, { useState } from 'react'
import '../styles/Interface.css' // We'll create this

export const Interface = () => {
    const [mobileMenuOpen, setMobileMenuOpen] = useState(false)

    return (
        <div className="interface">
            <header className="header">
                <div className="brand-block">
                    <img src="/apple-touch-icon.png" alt="AgentLayer logo" className="brand-mark" />
                    <span className="brand-text">AgentLayer</span>
                </div>

                <nav className="nav desktop-only">
                    <a href="#product" className="nav-item">Product</a>
                    <a href="#use-cases" className="nav-item">Use Cases</a>
                    <a href="#how-to-use" className="nav-item">How to use</a>
                    <a href="#about-agent-layer" className="nav-item">About</a>
                </nav>

                <button className="btn-download desktop-only">
                    Install
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
                        <img src="/apple-touch-icon.png" alt="AgentLayer logo" className="brand-mark brand-mark-menu" />
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
                        <a href="#about-agent-layer" className="mobile-nav-link">About</a>
                    </nav>
                </div>
            </div>

            <main className="hero">
                <div className="hero-content">
                    <div className="hero-logo-row">
                        <span className="hero-brand-text">AgentLayer</span>
                    </div>

                    <h1 className="hero-headline">Economic infrastructure for the AI agents era.</h1>

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
                            <a href="#product">Product</a>
                            <a href="#use-cases">Use Cases</a>
                            <a href="#how-to-use">How to use</a>
                        </div>
                        <div className="link-column">
                            <a href="https://github.com" target="_blank" rel="noreferrer">GitHub</a>
                            <a href="#">Blog</a>
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

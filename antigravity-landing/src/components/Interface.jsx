import React from 'react'
import '../styles/Interface.css' // We'll create this

export const Interface = () => {
    return (
        <div className="interface">
            <header className="header">
                <div className="logo">
                    {/* Simple SVG Logo Placeholder mimicking Google Antigravity */}
                    <svg width="150" height="24" viewBox="0 0 200 30" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <text x="0" y="20" fill="#5F6368" fontSize="20" fontFamily="sans-serif" fontWeight="bold">Google</text>
                        <text x="75" y="20" fill="#5F6368" fontSize="20" fontFamily="sans-serif">Antigravity</text>
                    </svg>
                </div>
                <nav className="nav">
                    <a href="#">Product</a>
                    <a href="#">Use Cases</a>
                    <a href="#">Pricing</a>
                    <a href="#">Blog</a>
                    <a href="#">Resources</a>
                </nav>
                <button className="btn-download">Download ↓</button>
            </header>

            <main className="hero">
                <div className="hero-content">
                    <div className="hero-logo">
                        {/* Large Center Logo */}
                        <svg width="60" height="60" viewBox="0 0 60 60" fill="none" xmlns="http://www.w3.org/2000/svg">
                            <path d="M30 0L60 60H0L30 0Z" fill="url(#paint0_linear)" />
                            <defs>
                                <linearGradient id="paint0_linear" x1="30" y1="0" x2="30" y2="60" gradientUnits="userSpaceOnUse">
                                    <stop stopColor="#4285F4" />
                                    <stop offset="1" stopColor="#34A853" />
                                </linearGradient>
                            </defs>
                        </svg>
                        <span className="hero-title-text">AgentLayer</span>
                    </div>

                    <h1>You have successfully authenticated.</h1>

                    <p className="subtitle">
                        You should be redirected back to the product. <a href="#">Click here</a> if not working.
                    </p>

                    <div className="footer-links">
                        <a href="#">Docs</a>
                        <span className="separator">|</span>
                        <a href="#">Twitter</a>
                    </div>
                </div>
            </main>

        </div>
    )
}

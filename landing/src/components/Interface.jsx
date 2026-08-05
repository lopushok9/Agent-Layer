import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import '../styles/Interface.css' // We'll create this

const FRAMEWORKS = ['OpenClaw', 'Claude Code', 'Codex', 'Hermes']
const NETWORKS = ['Base', 'Solana', 'Ethereum', 'Robinhood']
const INSTALL_COMMAND = 'npx --yes @agentlayer.tech/wallet@latest install'

// Every entry here is a protocol the wallet actually integrates.
// Marks live in /logos; an entry without one still renders as a plain name.
const ONCHAIN_TOOLS = [
    { name: 'Uniswap', logo: '/logos/uniswap.webp' },
    { name: 'Jupiter', logo: '/logos/jupiter.webp' },
    { name: 'Aave', logo: '/logos/aave.webp' },
    { name: 'Lido', logo: '/logos/lido.webp' },
    { name: 'Kamino', logo: '/logos/kamino.webp' },
    { name: 'LI.FI', logo: '/logos/lifi.webp' },
    { name: 'Morpho', logo: '/logos/morpho.webp' },
    { name: 'Flash Trade', logo: '/logos/flash-trade.webp' },
]

// Only GitHub is configured in production; X stays out of the copy until it is.
const BONUS_STEPS = ['Connect GitHub', 'Claim your code', 'Run the installer']

const ONCHAIN_CAPABILITIES = [
    {
        title: 'Isolated liquidity',
        body: 'Access to the best markets, like Morpho and Kamino.',
    },
    {
        title: 'Zero-fee swaps',
        body: 'Including cross-chain swaps.',
    },
    {
        title: 'Tokenized assets',
        body: 'Access to commodities and tokenized stocks.',
    },
]

const X402_CASES = [
    {
        limit: 'The model can’t generate images',
        action: 'It pays an image provider per render.',
    },
    {
        limit: 'Need transcription for that audio?',
        action: 'It finds a speech-to-text service on the x402 marketplace.',
    },
    {
        limit: 'Cloudflare blocks the source',
        action: 'It reads the page through a webcrawl x402 endpoint.',
    },
]

// Prerendering runs this component on the server, where layout effects do not exist.
const useIsomorphicLayoutEffect = typeof window === 'undefined' ? useEffect : useLayoutEffect

const prefersReducedMotion = () =>
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches

/**
 * Counts up to `target` once on mount. Starts at the final value so the
 * prerendered HTML (and no-JS / reduced-motion visitors) always shows the real number.
 */
const useCountUp = (target, { duration = 1100, delay = 0 } = {}) => {
    const [value, setValue] = useState(target)
    const frameRef = useRef(0)
    const timerRef = useRef(0)

    useIsomorphicLayoutEffect(() => {
        if (prefersReducedMotion()) return undefined

        setValue(0)

        const run = () => {
            const start = performance.now()

            const step = (now) => {
                const progress = Math.min((now - start) / duration, 1)
                // ease-out-expo: fast arrival, smooth settle
                const eased = progress === 1 ? 1 : 1 - Math.pow(2, -10 * progress)
                setValue(Math.round(target * eased))
                if (progress < 1) frameRef.current = requestAnimationFrame(step)
            }

            frameRef.current = requestAnimationFrame(step)
        }

        timerRef.current = window.setTimeout(run, delay)

        return () => {
            window.clearTimeout(timerRef.current)
            cancelAnimationFrame(frameRef.current)
        }
    }, [target, duration, delay])

    return value
}

/**
 * Counts up to `target` the first time the element reaches the viewport.
 *
 * Like the reveal below, it only resets to zero once it knows it can animate
 * back up, and only while the figure is still off-screen — so a visitor never
 * sees a stranded 0, and prerendered HTML carries the real number.
 */
const useCountUpOnView = (target, { duration = 1500, decimals = 0 } = {}) => {
    const ref = useRef(null)
    const [value, setValue] = useState(target)

    useIsomorphicLayoutEffect(() => {
        const node = ref.current
        if (!node) return undefined
        if (prefersReducedMotion() || typeof IntersectionObserver === 'undefined') return undefined

        let frame = 0

        const run = () => {
            const start = performance.now()
            const step = (now) => {
                const progress = Math.min((now - start) / duration, 1)
                // ease-out-expo: quick climb, long settle onto the final figure
                const eased = progress === 1 ? 1 : 1 - Math.pow(2, -10 * progress)
                setValue(Number((target * eased).toFixed(decimals)))
                if (progress < 1) frame = requestAnimationFrame(step)
            }
            frame = requestAnimationFrame(step)
        }

        const box = node.getBoundingClientRect()
        if (box.top < window.innerHeight && box.bottom > 0) {
            // Already on screen at mount — animate straight away rather than
            // blanking a figure the visitor can see.
            run()
            return () => cancelAnimationFrame(frame)
        }

        setValue(0)

        const observer = new IntersectionObserver(
            ([entry]) => {
                if (!entry.isIntersecting) return
                observer.disconnect()
                run()
            },
            { rootMargin: '0px 0px -20% 0px' },
        )

        observer.observe(node)

        return () => {
            observer.disconnect()
            cancelAnimationFrame(frame)
        }
    }, [target, duration, decimals])

    return [ref, value]
}

/**
 * Reveals an element the first time it scrolls into view.
 *
 * The hidden state is armed from JS rather than rendered, so the section stays
 * visible in the prerendered HTML and for anyone without JS, reduced motion or
 * IntersectionObserver — it can only ever hide content it can also reveal.
 */
const useReveal = () => {
    const ref = useRef(null)

    useEffect(() => {
        const node = ref.current
        if (!node) return undefined
        if (prefersReducedMotion() || typeof IntersectionObserver === 'undefined') return undefined

        node.classList.add('is-armed')

        const observer = new IntersectionObserver(
            ([entry]) => {
                if (!entry.isIntersecting) return
                node.classList.add('is-in')
                observer.disconnect()
            },
            { rootMargin: '-12% 0px -12% 0px' },
        )

        observer.observe(node)
        return () => observer.disconnect()
    }, [])

    return ref
}

const ToolsGroup = ({ duplicate }) => (
    <div className="oc-tools-group" aria-hidden={duplicate || undefined}>
        {ONCHAIN_TOOLS.map((tool) => (
            <span className="oc-tool" key={tool.name}>
                {tool.logo && (
                    <img
                        className="oc-tool-logo"
                        src={tool.logo}
                        alt=""
                        aria-hidden="true"
                        width="20"
                        height="20"
                    />
                )}
                <span className="oc-tool-name">{tool.name}</span>
            </span>
        ))}
    </div>
)

const MarqueeGroup = ({ duplicate }) => (
    <div className="hh-marquee-group" aria-hidden={duplicate || undefined}>
        {Array.from({ length: 2 }).flatMap((_, cycle) =>
            FRAMEWORKS.map((name) => (
                <span className="hh-marquee-cell" key={`${cycle}-${name}`}>
                    <span className="hh-marquee-item">{name}</span>
                    <span className="hh-marquee-sep" aria-hidden="true">/</span>
                </span>
            )),
        )}
    </div>
)

export const Interface = ({ onInstallClick }) => {
    const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
    const [installCopied, setInstallCopied] = useState(false)
    const installs = useCountUp(10000, { duration: 1200, delay: 380 })
    const tools = useCountUp(60, { duration: 1000, delay: 480 })
    const x402Ref = useReveal()
    const onchainRef = useReveal()
    const bonusRef = useReveal()
    const [apyRef, apy] = useCountUpOnView(10.5, { duration: 1600, decimals: 1 })

    const handleInstallCopy = async () => {
        const command = INSTALL_COMMAND

        try {
            await navigator.clipboard.writeText(command)
            setInstallCopied(true)
            window.setTimeout(() => setInstallCopied(false), 1800)
        } catch {
            setInstallCopied(false)
        }
    }

    return (
        <div className="interface">
            <header className="header">
                <div className="brand-block">
                    <img src="/apple-touch-icon.png" alt="AgentLayer logo" className="brand-mark" />
                    <span className="wordmark-lockup">
                        <span className="brand-text">AgentLayer</span>
                        <span className="wordmark-beta" aria-hidden="true">β</span>
                    </span>
                </div>

                <nav className="nav desktop-only">
                    <a href="/wallet" className="nav-item">Wallet</a>
                    <a href="/use-cases" className="nav-item">Use Cases</a>
                    <a href="/skill.md" className="nav-item">For LLMs</a>
                    <a href="/for-investors" className="nav-item">For Investors</a>
                    <a href="/about" className="nav-item">About</a>
                </nav>

                <button type="button" className="btn-download desktop-only" onClick={onInstallClick}>
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
                        <span className="wordmark-lockup">
                            <span className="brand-text-menu">AgentLayer</span>
                            <span className="wordmark-beta" aria-hidden="true">β</span>
                        </span>
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
                        <a href="/wallet" className="mobile-nav-link" onClick={() => setMobileMenuOpen(false)}>Wallet</a>
                        <a href="/use-cases" className="mobile-nav-link" onClick={() => setMobileMenuOpen(false)}>Use Cases</a>
                        <a href="/skill.md" className="mobile-nav-link" onClick={() => setMobileMenuOpen(false)}>For LLMs</a>
                        <a href="/for-investors" className="mobile-nav-link" onClick={() => setMobileMenuOpen(false)}>For Investors</a>
                        <a href="/about" className="mobile-nav-link" onClick={() => setMobileMenuOpen(false)}>About</a>
                    </nav>
                </div>
            </div>

            <main className="hero-home">
                <div className="hh-grid">
                    {/* 01 — Thesis */}
                    <section className="hh-thesis">
                        <p className="hh-eyebrow hh-rise" style={{ '--d': '0.10s' }}>
                            <span className="hh-pulse" aria-hidden="true" />
                            {NETWORKS.map((network, index) => (
                                <span className="hh-eyebrow-cell" key={network}>
                                    {index > 0 && <i aria-hidden="true">/</i>}
                                    {network}
                                </span>
                            ))}
                        </p>

                        <h1 className="hh-title hh-rise" style={{ '--d': '0.18s' }}>Wallet for agents</h1>

                        <p className="hh-lede hh-rise" style={{ '--d': '0.26s' }}>
                            Make payments via x402, use stablecoins, swap assets, earn yield with defi and buy tokenized stocks across the most popular chains.
                        </p>

                        <div className="hh-actions hh-rise" style={{ '--d': '0.34s' }}>
                            <button
                                type="button"
                                className={`hh-install ${installCopied ? 'is-copied' : ''}`}
                                aria-label="Copy install command"
                                onClick={handleInstallCopy}
                            >
                                <code>{INSTALL_COMMAND}</code>
                                <span className="hh-install-copy" aria-hidden="true">
                                    {installCopied ? (
                                        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
                                            <path d="M3.5 8.25L6.25 11L12.5 4.75" stroke="#111213" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                                        </svg>
                                    ) : (
                                        <img src="/copy-svgrepo-com.svg" alt="" />
                                    )}
                                </span>
                                <span className="hh-install-status" role="status">
                                    {installCopied ? 'Copied' : ''}
                                </span>
                            </button>

                            <div className="hh-links">
                                <a href="https://docs.agent-layer.tech" target="_blank" rel="noreferrer">Docs</a>
                                <a href="https://x.com/agentlayer_ai" target="_blank" rel="noreferrer">Blog</a>
                            </div>
                        </div>
                    </section>

                    {/* 03 + 04 — Numbers */}
                    <aside className="hh-stats" aria-label="Key numbers">
                        <div className="hh-stat hh-rise" style={{ '--d': '0.34s' }}>
                            <span className="hh-stat-label">Installs</span>
                            <span className="hh-stat-value">
                                <span className="hh-stat-num">{installs.toLocaleString('en-US')}</span>
                                <span className="hh-stat-plus" aria-hidden="true">+</span>
                            </span>
                            <span className="hh-stat-note">agents running the wallet</span>
                        </div>

                        <div className="hh-stat hh-rise" style={{ '--d': '0.44s' }}>
                            <span className="hh-stat-label">On-chain tools</span>
                            <span className="hh-stat-value">
                                <span className="hh-stat-num">{tools}</span>
                                <span className="hh-stat-plus" aria-hidden="true">+</span>
                            </span>
                            <span className="hh-stat-note">swaps · lending · staking</span>
                        </div>

                        {/* 02 — Supported frameworks */}
                        <section className="hh-frameworks hh-rise" style={{ '--d': '0.54s' }} aria-label="Supported frameworks">
                            <span className="hh-stat-label">Runs on</span>
                            <div className="hh-marquee">
                                <div className="hh-marquee-track">
                                    <MarqueeGroup />
                                    <MarqueeGroup duplicate />
                                </div>
                            </div>
                        </section>
                    </aside>
                </div>
            </main>

            {/* x402 — what a wallet unlocks */}
            <section className="x4" ref={x402Ref} aria-labelledby="x4-title">
                <div className="x4-head">
                    <span className="x4-eyebrow">Discover thousands of services with x402</span>
                    <h2 className="x4-title" id="x4-title">
                        An agent with a wallet<br />stops hitting walls.
                    </h2>
                    <p className="x4-lede">
                        Every capability your model lacks is a service it can buy — per request, no keys, no subscriptions.
                    </p>

                    <img className="x4-art" src="/agent-card.svg" alt="" aria-hidden="true" width="985" height="540" />
                </div>

                <ol className="x4-list">
                    {X402_CASES.map((item, index) => (
                        <li className="x4-row" key={item.limit} style={{ '--i': index }}>
                            <span className="x4-index" aria-hidden="true">
                                {String(index + 1).padStart(2, '0')}
                            </span>
                            <span className="x4-body">
                                <span className="x4-limit">{item.limit}</span>
                                <span className="x4-action">{item.action}</span>
                            </span>
                        </li>
                    ))}
                </ol>

                <p className="x4-kicker">
                    Money is the capability layer.
                    <a href="/use-cases">See all use cases</a>
                </p>
            </section>

            {/* On-chain capabilities */}
            <section className="oc" ref={onchainRef} aria-labelledby="oc-title">
                <div className="oc-tools">
                    <span className="oc-tools-label">Tools your agent gets with AgentLayer</span>
                    <div className="oc-marquee">
                        <div className="oc-marquee-track">
                            <ToolsGroup />
                            <ToolsGroup duplicate />
                        </div>
                    </div>
                </div>

                <div className="oc-lead">
                    <div className="oc-lead-text">
                        <span className="oc-eyebrow">On-chain</span>
                        <h2 className="oc-title" id="oc-title">Agents generate yield</h2>
                        <p className="oc-lede">
                            Your agent plugs into battle-tested DeFi infrastructure — swaps, lending, borrowing and more.
                        </p>
                    </div>

                    <p className="oc-figure" ref={apyRef}>
                        <span className="oc-num">{apy.toFixed(1)}</span>
                        <span className="oc-pct" aria-hidden="true">%</span>
                        <span className="oc-apy">APY</span>
                    </p>
                </div>

                <ul className="oc-grid">
                    {ONCHAIN_CAPABILITIES.map((item, index) => (
                        <li className="oc-cell" key={item.title} style={{ '--i': index }}>
                            <h3 className="oc-cell-title">{item.title}</h3>
                            <p className="oc-cell-body">{item.body}</p>
                        </li>
                    ))}
                </ul>
            </section>

            {/* Welcome bonus — the page's one call to action */}
            <section className="wb" ref={bonusRef} aria-labelledby="wb-title">
                <div className="wb-lead">
                    <div className="wb-copy">
                        <span className="wb-eyebrow">Welcome bonus</span>
                        <h2 className="wb-title" id="wb-title">Try agentic commerce</h2>
                        <p className="wb-lede">
                            New wallets come with a bonus on Base. Connect GitHub to claim a one-time
                            code, and let your agent make its first payments over x402.
                        </p>
                    </div>

                    <a className="wb-cta" href="/onboard">
                        Claim your bonus
                        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true" xmlns="http://www.w3.org/2000/svg">
                            <path d="M1 7H13M13 7L8 2M13 7L8 12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                    </a>
                </div>

                <ol className="wb-steps">
                    {BONUS_STEPS.map((step, index) => (
                        <li className="wb-step" key={step} style={{ '--i': index }}>
                            <span className="wb-step-num" aria-hidden="true">
                                {String(index + 1).padStart(2, '0')}
                            </span>
                            <span className="wb-step-text">{step}</span>
                        </li>
                    ))}
                </ol>
            </section>

            {/* Continuation Section (Reference Implementation) */}
            <div className="extended-section">
                <div className="extended-header">
                    <h2 className="finance-title">finance</h2>
                    <div className="extended-links">
                        <div className="link-column">
                        <a href="/wallet">Wallet</a>
                        <a href="/use-cases">Use Cases</a>
                        <a href="/skill.md">For LLMs</a>
                        </div>
                        <div className="link-column">
                            <a href="https://docs.agent-layer.tech" target="_blank" rel="noreferrer">Docs</a>
                            <a href="https://github.com/lopushok9/Agent-Layer" target="_blank" rel="noreferrer">GitHub</a>
                            <a href="https://x.com/agentlayer_ai" target="_blank" rel="noreferrer">Blog</a>
                        </div>
                    </div>
                </div>

                <div className="huge-text-container">
                    <h1 className="huge-antigravity">for ai agents</h1>
                </div>

                    <div className="extended-footer">
                        <div className="footer-brand">AgentLayer</div>
                        <div className="footer-bottom-links">
                            <a href="/about">About AgentLayer</a>
                            <a href="/terms">Terms</a>
                        </div>
                        <span className="footer-ca" aria-label="Contract address">
                          <span className="footer-ca-label">CA</span>
                          <span className="footer-ca-value">444DPguaifQZ5NicFicD9Kni6emKexyq<wbr />qG4dEkUaBAGS</span>
                        </span>
                    </div>
            </div>

        </div >
    )
}

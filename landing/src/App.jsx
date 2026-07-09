import { useEffect, useState } from 'react'
import { Particles } from './components/Particles'
import { Interface } from './components/Interface'
import { InstallModal } from './components/InstallModal'
import { ProductPage } from './components/ProductPage'
import { WalletPage } from './components/WalletPage'
import { UseCasesPage } from './components/UseCasesPage'
import { HowToUsePage } from './components/HowToUsePage'
import { AboutAgentLayerPage } from './components/AboutAgentLayerPage'
import { ForInvestorsPage } from './components/ForInvestorsPage'
import { TermsPage } from './components/TermsPage'
import './index.css'

const SITE_ORIGIN = 'https://www.agent-layer.tech'
const DEFAULT_DESCRIPTION = 'AgentLayer is wallet for agents, like OpenClaw and Claude Code. Make payments via x402, use stablecoins, swap assets, earn yield with DeFi, and buy tokenized stocks across the most popular chains.'

const ROUTES = {
  home: {
    path: '/',
    title: 'AgentLayer | Wallet for Agents',
    description: DEFAULT_DESCRIPTION,
  },
  wallet: {
    path: '/wallet',
    title: 'AgentLayer Wallet | Local Wallet for Agents',
    description: 'A local wallet runtime for OpenClaw and Claude Code agents with balances, swaps, staking, approvals, and hardened execution flows.',
  },
  product: {
    path: '/mcp',
    title: 'AgentLayer MCP | Infrastructure for Agentic Finance',
    description: 'Query prices, chains, wallets, and DeFi data through AgentLayer MCP, a protocol-level finance stack built for AI agents.',
  },
  'use-cases': {
    path: '/use-cases',
    title: 'AgentLayer Use Cases | What Agents Build',
    description: 'See how AI agents use AgentLayer for portfolio monitoring, DeFi yield optimization, on-chain analysis, and agent-native coordination.',
  },
  'how-to-use': {
    path: '/how-to-use',
    title: 'How to Use AgentLayer | Connect Your Agent',
    description: 'Connect AgentLayer to OpenClaw, Claude Code, Cursor, Windsurf, and other MCP clients with a single config block.',
  },
  'for-investors': {
    path: '/for-investors',
    title: 'AgentLayer for Investors | Investor Overview',
    description: 'Investor overview for AgentLayer: the AI-native wallet and finance layer for agentic payments, DeFi activity, and onchain execution.',
  },
  about: {
    path: '/about',
    title: 'About AgentLayer | Finance Layer for Agents',
    description: 'Learn how AgentLayer connects autonomous agents to market data, DeFi context, wallet execution, and structured financial tooling.',
  },
  terms: {
    path: '/terms',
    title: 'AgentLayer Terms | Risk Disclosure',
    description: 'Review AgentLayer beta terms, risk disclosures, financial disclaimer language, and data availability caveats.',
  },
}

const PATH_TO_PAGE = Object.fromEntries(
  Object.entries(ROUTES).map(([page, route]) => [route.path, page]),
)

const LEGACY_HASH_REDIRECTS = {
  '#wallet': ROUTES.wallet.path,
  '#mcp': ROUTES.product.path,
  '#product': ROUTES.product.path,
  '#use-cases': ROUTES['use-cases'].path,
  '#how-to-use': ROUTES['how-to-use'].path,
  '#for-investors': ROUTES['for-investors'].path,
  '#about-agent-layer': ROUTES.about.path,
  '#terms': ROUTES.terms.path,
}

const PATH_REDIRECTS = {
  '/product': ROUTES.product.path,
  '/about-agent-layer': ROUTES.about.path,
}

function normalizePathname(pathname) {
  if (!pathname || pathname === '/') return '/'
  return pathname.endsWith('/') ? pathname.slice(0, -1) : pathname
}

function ensureMetaTag(selector, attributeName, attributeValue) {
  let element = document.head.querySelector(selector)
  if (!element) {
    element = document.createElement('meta')
    element.setAttribute(attributeName, attributeValue)
    document.head.appendChild(element)
  }
  return element
}

function updateDocumentMetadata(page) {
  const route = ROUTES[page]
  const canonicalUrl = `${SITE_ORIGIN}${route.path}`

  document.title = route.title

  ensureMetaTag('meta[name="description"]', 'name', 'description').setAttribute('content', route.description)
  ensureMetaTag('meta[property="og:title"]', 'property', 'og:title').setAttribute('content', route.title)
  ensureMetaTag('meta[property="og:description"]', 'property', 'og:description').setAttribute('content', route.description)
  ensureMetaTag('meta[property="og:url"]', 'property', 'og:url').setAttribute('content', canonicalUrl)
  ensureMetaTag('meta[name="twitter:title"]', 'name', 'twitter:title').setAttribute('content', route.title)
  ensureMetaTag('meta[name="twitter:description"]', 'name', 'twitter:description').setAttribute('content', route.description)

  const canonical = document.head.querySelector('link[rel="canonical"]')
  if (canonical) {
    canonical.setAttribute('href', canonicalUrl)
  }
}

function resolveRoute(locationLike) {
  const normalizedPath = normalizePathname(locationLike.pathname)
  const legacyPath = normalizedPath === '/' ? LEGACY_HASH_REDIRECTS[locationLike.hash] : undefined

  if (legacyPath) {
    return { redirectPath: legacyPath }
  }

  const redirectedPath = PATH_REDIRECTS[normalizedPath]
  if (redirectedPath) {
    return { redirectPath: redirectedPath }
  }

  const page = PATH_TO_PAGE[normalizedPath]
  if (page) {
    return { page, path: ROUTES[page].path }
  }

  return { redirectPath: ROUTES.home.path }
}

function App() {
  const [page, setPage] = useState(() => {
    const route = resolveRoute(window.location)
    return route.page ?? 'home'
  })
  const [installModalOpen, setInstallModalOpen] = useState(false)

  useEffect(() => {
    const syncRoute = ({ replace = false } = {}) => {
      const route = resolveRoute(window.location)

      if (route.redirectPath) {
        const nextMethod = replace ? 'replaceState' : 'pushState'
        window.history[nextMethod](null, '', route.redirectPath)
        const redirectedRoute = resolveRoute({
          pathname: route.redirectPath,
          hash: '',
        })
        setPage(redirectedRoute.page)
        return
      }

      setPage(route.page)
    }

    const onPopState = () => syncRoute({ replace: true })

    const onDocumentClick = (event) => {
      const anchor = event.target.closest('a[href]')
      if (!anchor) return
      if (anchor.target === '_blank' || anchor.hasAttribute('download')) return

      const href = anchor.getAttribute('href')
      if (!href || href.startsWith('#') || href.startsWith('mailto:') || href.startsWith('tel:')) return

      const nextUrl = new URL(anchor.href, window.location.origin)
      if (nextUrl.origin !== window.location.origin) return

      const currentUrl = new URL(window.location.href)
      if (nextUrl.pathname === currentUrl.pathname && nextUrl.search === currentUrl.search && nextUrl.hash === currentUrl.hash) {
        return
      }

      event.preventDefault()
      window.history.pushState(null, '', `${nextUrl.pathname}${nextUrl.search}${nextUrl.hash}`)
      syncRoute()
      window.scrollTo(0, 0)
    }

    syncRoute({ replace: true })
    window.addEventListener('popstate', onPopState)
    document.addEventListener('click', onDocumentClick)

    return () => {
      window.removeEventListener('popstate', onPopState)
      document.removeEventListener('click', onDocumentClick)
    }
  }, [])

  useEffect(() => {
    updateDocumentMetadata(page)
  }, [page])

  return (
    <>
      <Particles />
      {page === 'wallet' && <WalletPage onInstallClick={() => setInstallModalOpen(true)} />}
      {page === 'product' && <ProductPage onInstallClick={() => setInstallModalOpen(true)} />}
      {page === 'use-cases' && <UseCasesPage onInstallClick={() => setInstallModalOpen(true)} />}
      {page === 'how-to-use' && <HowToUsePage onInstallClick={() => setInstallModalOpen(true)} />}
      {page === 'for-investors' && <ForInvestorsPage onInstallClick={() => setInstallModalOpen(true)} />}
      {page === 'about' && <AboutAgentLayerPage onInstallClick={() => setInstallModalOpen(true)} />}
      {page === 'terms' && <TermsPage onInstallClick={() => setInstallModalOpen(true)} />}
      {page === 'home' && <Interface onInstallClick={() => setInstallModalOpen(true)} />}
      <InstallModal isOpen={installModalOpen} onClose={() => setInstallModalOpen(false)} />
    </>
  )
}

export default App

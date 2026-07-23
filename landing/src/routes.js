export const SITE_ORIGIN = 'https://www.agent-layer.tech'

export const DEFAULT_DESCRIPTION = 'AgentLayer is wallet for agents, like OpenClaw and Claude Code. Make payments via x402, use stablecoins, swap assets, earn yield with DeFi, and buy tokenized stocks across the most popular chains.'

export const ROUTES = {
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
  onboard: {
    path: '/onboard',
    title: 'AgentLayer Welcome Bonus | Connect GitHub or X',
    description: 'Connect GitHub or X, receive a one-time invite code, and bind it to your local AgentLayer wallet on Base.',
  },
}

export const PATH_TO_PAGE = Object.fromEntries(
  Object.entries(ROUTES).map(([page, route]) => [route.path, page]),
)

export const PRERENDER_PAGES = Object.keys(ROUTES)
export const PRERENDER_PATHS = PRERENDER_PAGES.map((page) => ROUTES[page].path)

export const LEGACY_HASH_REDIRECTS = {
  '#wallet': ROUTES.wallet.path,
  '#mcp': ROUTES.product.path,
  '#product': ROUTES.product.path,
  '#use-cases': ROUTES['use-cases'].path,
  '#how-to-use': ROUTES['how-to-use'].path,
  '#for-investors': ROUTES['for-investors'].path,
  '#about-agent-layer': ROUTES.about.path,
  '#terms': ROUTES.terms.path,
}

export const PATH_REDIRECTS = {
  '/product': ROUTES.product.path,
  '/about-agent-layer': ROUTES.about.path,
}

export function normalizePathname(pathname) {
  if (!pathname || pathname === '/') return '/'
  return pathname.endsWith('/') ? pathname.slice(0, -1) : pathname
}

export function resolveRoute(locationLike) {
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

export function getMetadataForPage(page) {
  const route = ROUTES[page] ?? ROUTES.home
  return {
    ...route,
    canonicalUrl: `${SITE_ORIGIN}${route.path}`,
  }
}

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
import { getMetadataForPage, resolveRoute } from './routes'
import './index.css'

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
  const metadata = getMetadataForPage(page)

  document.title = metadata.title

  ensureMetaTag('meta[name="description"]', 'name', 'description').setAttribute('content', metadata.description)
  ensureMetaTag('meta[property="og:title"]', 'property', 'og:title').setAttribute('content', metadata.title)
  ensureMetaTag('meta[property="og:description"]', 'property', 'og:description').setAttribute('content', metadata.description)
  ensureMetaTag('meta[property="og:url"]', 'property', 'og:url').setAttribute('content', metadata.canonicalUrl)
  ensureMetaTag('meta[name="twitter:title"]', 'name', 'twitter:title').setAttribute('content', metadata.title)
  ensureMetaTag('meta[name="twitter:description"]', 'name', 'twitter:description').setAttribute('content', metadata.description)

  const canonical = document.head.querySelector('link[rel="canonical"]')
  if (canonical) {
    canonical.setAttribute('href', metadata.canonicalUrl)
  }
}

function App({ initialPage, initialPath, suppressNavigation = false }) {
  const [page, setPage] = useState(() => {
    if (initialPage) {
      return initialPage
    }

    if (typeof window === 'undefined') {
      const route = resolveRoute({ pathname: initialPath ?? '/', hash: '' })
      return route.page ?? 'home'
    }

    const route = resolveRoute(window.location)
    return route.page ?? 'home'
  })
  const [installModalOpen, setInstallModalOpen] = useState(false)

  useEffect(() => {
    if (suppressNavigation || typeof window === 'undefined') {
      return undefined
    }

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
      if (nextUrl.pathname.endsWith('.md') || nextUrl.pathname.endsWith('.txt')) return

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
  }, [suppressNavigation])

  useEffect(() => {
    if (typeof document === 'undefined') {
      return
    }
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
      {installModalOpen && (
        <InstallModal isOpen={installModalOpen} onClose={() => setInstallModalOpen(false)} />
      )}
    </>
  )
}

export default App

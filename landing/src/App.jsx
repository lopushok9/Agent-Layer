import { useState, useEffect } from 'react'
import { Particles } from './components/Particles'
import { Interface } from './components/Interface'
import { InstallModal } from './components/InstallModal'
import { ProductPage } from './components/ProductPage'
import { WalletPage } from './components/WalletPage'
import { UseCasesPage } from './components/UseCasesPage'
import { HowToUsePage } from './components/HowToUsePage'
import { AboutAgentLayerPage } from './components/AboutAgentLayerPage'
import { TermsPage } from './components/TermsPage'
import './index.css'

function App() {
  const getPage = () => {
    const hash = window.location.hash
    if (hash === '#wallet') return 'wallet'
    if (hash === '#mcp') return 'product'
    if (hash === '#product') return 'product'
    if (hash === '#use-cases') return 'use-cases'
    if (hash === '#how-to-use') return 'how-to-use'
    if (hash === '#about-agent-layer') return 'about-agent-layer'
    if (hash === '#terms') return 'terms'
    return 'home'
  }

  const [page, setPage] = useState(getPage)
  const [installModalOpen, setInstallModalOpen] = useState(false)

  useEffect(() => {
    const onHash = () => setPage(getPage())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  return (
    <>
      <Particles />
      {page === 'wallet' && <WalletPage onInstallClick={() => setInstallModalOpen(true)} />}
      {page === 'product' && <ProductPage onInstallClick={() => setInstallModalOpen(true)} />}
      {page === 'use-cases' && <UseCasesPage onInstallClick={() => setInstallModalOpen(true)} />}
      {page === 'how-to-use' && <HowToUsePage onInstallClick={() => setInstallModalOpen(true)} />}
      {page === 'about-agent-layer' && <AboutAgentLayerPage onInstallClick={() => setInstallModalOpen(true)} />}
      {page === 'terms' && <TermsPage onInstallClick={() => setInstallModalOpen(true)} />}
      {page === 'home' && <Interface onInstallClick={() => setInstallModalOpen(true)} />}
      <InstallModal isOpen={installModalOpen} onClose={() => setInstallModalOpen(false)} />
    </>
  )
}

export default App

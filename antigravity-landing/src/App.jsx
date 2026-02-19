import { useState, useEffect } from 'react'
import { Particles } from './components/Particles'
import { Interface } from './components/Interface'
import { ProductPage } from './components/ProductPage'
import { UseCasesPage } from './components/UseCasesPage'
import { HowToUsePage } from './components/HowToUsePage'
import { AboutAgentLayerPage } from './components/AboutAgentLayerPage'
import { TermsPage } from './components/TermsPage'
import './index.css'

function App() {
  const getPage = () => {
    const hash = window.location.hash
    if (hash === '#product') return 'product'
    if (hash === '#use-cases') return 'use-cases'
    if (hash === '#how-to-use') return 'how-to-use'
    if (hash === '#about-agent-layer') return 'about-agent-layer'
    if (hash === '#terms') return 'terms'
    return 'home'
  }

  const [page, setPage] = useState(getPage)

  useEffect(() => {
    const onHash = () => setPage(getPage())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  return (
    <>
      <Particles />
      {page === 'product' && <ProductPage />}
      {page === 'use-cases' && <UseCasesPage />}
      {page === 'how-to-use' && <HowToUsePage />}
      {page === 'about-agent-layer' && <AboutAgentLayerPage />}
      {page === 'terms' && <TermsPage />}
      {page === 'home' && <Interface />}
    </>
  )
}

export default App

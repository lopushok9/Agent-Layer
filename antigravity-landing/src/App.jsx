import { useState, useEffect } from 'react'
import { Particles } from './components/Particles'
import { Interface } from './components/Interface'
import { ProductPage } from './components/ProductPage'
import { UseCasesPage } from './components/UseCasesPage'
import { HowToUsePage } from './components/HowToUsePage'
import './index.css'

function App() {
  const getPage = () => {
    const hash = window.location.hash
    if (hash === '#product') return 'product'
    if (hash === '#use-cases') return 'use-cases'
    if (hash === '#how-to-use') return 'how-to-use'
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
      {page === 'home' && <Interface />}
    </>
  )
}

export default App

import { useState, useEffect } from 'react'
import { Particles } from './components/Particles'
import { Interface } from './components/Interface'
import { ProductPage } from './components/ProductPage'
import { UseCasesPage } from './components/UseCasesPage'
import './index.css'

function App() {
  const getPage = () => {
    const hash = window.location.hash
    if (hash === '#product') return 'product'
    if (hash === '#use-cases') return 'use-cases'
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
      {page === 'home' && <Interface />}
    </>
  )
}

export default App

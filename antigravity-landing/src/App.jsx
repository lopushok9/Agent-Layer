import { useState, useEffect } from 'react'
import { Particles } from './components/Particles'
import { Interface } from './components/Interface'
import { ProductPage } from './components/ProductPage'
import './index.css'

function App() {
  const [page, setPage] = useState(
    window.location.hash === '#product' ? 'product' : 'home'
  )

  useEffect(() => {
    const onHash = () => {
      setPage(window.location.hash === '#product' ? 'product' : 'home')
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  return (
    <>
      <Particles />
      {page === 'product' ? <ProductPage /> : <Interface />}
    </>
  )
}

export default App

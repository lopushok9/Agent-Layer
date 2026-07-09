import { createElement } from 'react'
import { renderToString } from 'react-dom/server'
import App from './App.jsx'
import { getMetadataForPage, resolveRoute } from './routes.js'

function resolveRequestPath(url) {
  const requestedUrl = new URL(url, 'https://www.agent-layer.tech')
  let route = resolveRoute({
    pathname: requestedUrl.pathname,
    hash: requestedUrl.hash,
  })

  if (route.redirectPath) {
    route = resolveRoute({
      pathname: route.redirectPath,
      hash: '',
    })
  }

  return route
}

export function render(url) {
  const route = resolveRequestPath(url)
  const page = route.page ?? 'home'

  return {
    appHtml: renderToString(
      createElement(App, {
        initialPage: page,
        initialPath: route.path,
        suppressNavigation: true,
      }),
    ),
    metadata: getMetadataForPage(page),
  }
}

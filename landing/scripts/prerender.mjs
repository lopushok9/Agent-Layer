import { mkdir, readFile, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

const projectRoot = process.cwd()
const clientDistDir = path.join(projectRoot, 'dist')
const clientTemplatePath = path.join(clientDistDir, 'index.html')
const ssrOutDir = path.join(projectRoot, '.ssr')
const ssrEntryPath = path.join(ssrOutDir, 'entry-server.js')
const routesModulePath = path.join(projectRoot, 'src', 'routes.js')

function escapeHtml(value) {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
}

function escapeAttribute(value) {
  return escapeHtml(value).replaceAll('"', '&quot;')
}

function replacePattern(html, pattern, replacement) {
  if (!pattern.test(html)) {
    throw new Error(`Template pattern not found: ${pattern}`)
  }
  return html.replace(pattern, replacement)
}

function injectAppMarkup(template, appHtml) {
  return replacePattern(
    template,
    /<div id="root">\s*<\/div>/,
    `<div id="root">${appHtml}</div>`,
  )
}

function injectMetadata(template, metadata) {
  let html = template

  html = replacePattern(
    html,
    /<title>.*?<\/title>/s,
    `<title>${escapeHtml(metadata.title)}</title>`,
  )

  html = replacePattern(
    html,
    /<meta name="description" content="[^"]*" \/>/,
    `<meta name="description" content="${escapeAttribute(metadata.description)}" />`,
  )

  html = replacePattern(
    html,
    /<meta property="og:title" content="[^"]*" \/>/,
    `<meta property="og:title" content="${escapeAttribute(metadata.title)}" />`,
  )

  html = replacePattern(
    html,
    /<meta property="og:description" content="[^"]*" \/>/,
    `<meta property="og:description" content="${escapeAttribute(metadata.description)}" />`,
  )

  html = replacePattern(
    html,
    /<meta property="og:url" content="[^"]*" \/>/,
    `<meta property="og:url" content="${escapeAttribute(metadata.canonicalUrl)}" />`,
  )

  html = replacePattern(
    html,
    /<meta name="twitter:title" content="[^"]*" \/>/,
    `<meta name="twitter:title" content="${escapeAttribute(metadata.title)}" />`,
  )

  html = replacePattern(
    html,
    /<meta name="twitter:description" content="[^"]*" \/>/,
    `<meta name="twitter:description" content="${escapeAttribute(metadata.description)}" />`,
  )

  html = replacePattern(
    html,
    /<link rel="canonical" href="[^"]*" \/>/,
    `<link rel="canonical" href="${escapeAttribute(metadata.canonicalUrl)}" />`,
  )

  return html
}

function routePathToOutputFile(routePath) {
  if (routePath === '/') {
    return path.join(clientDistDir, 'index.html')
  }

  return path.join(clientDistDir, routePath.slice(1), 'index.html')
}

function routePathToCanonical(routePath, siteOrigin) {
  if (routePath === '/') {
    return `${siteOrigin}/`
  }

  return `${siteOrigin}${routePath}/`
}

function buildSitemapXml(siteOrigin, routePaths) {
  const urls = routePaths.map((routePath) => `  <url>\n    <loc>${routePathToCanonical(routePath, siteOrigin)}</loc>\n  </url>`)
  return `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls.join('\n')}\n</urlset>\n`
}

async function main() {
  const template = await readFile(clientTemplatePath, 'utf8')
  const serverEntry = await import(pathToFileURL(ssrEntryPath).href)
  const routesModule = await import(pathToFileURL(routesModulePath).href)

  for (const routePath of routesModule.PRERENDER_PATHS) {
    const { appHtml, metadata } = serverEntry.render(routePath)
    const html = injectMetadata(injectAppMarkup(template, appHtml), metadata)
    const outputFile = routePathToOutputFile(routePath)

    await mkdir(path.dirname(outputFile), { recursive: true })
    await writeFile(outputFile, html)
  }

  const sitemapXml = buildSitemapXml(routesModule.SITE_ORIGIN, routesModule.PRERENDER_PATHS)
  await writeFile(path.join(clientDistDir, 'sitemap.xml'), sitemapXml)
}

main().catch((error) => {
  console.error(error)
  process.exitCode = 1
})

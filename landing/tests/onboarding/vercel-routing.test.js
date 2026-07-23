import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import { describe, it } from 'node:test'

const testDirectory = path.dirname(fileURLToPath(import.meta.url))
const vercelConfigPath = path.resolve(testDirectory, '../../vercel.json')

describe('Vercel auth routing', () => {
  it('routes every Better Auth endpoint through the catch-all function', async () => {
    const config = JSON.parse(await readFile(vercelConfigPath, 'utf8'))
    assert.deepEqual(
      config.rewrites.find((rewrite) => rewrite.source === '/api/auth/:path*'),
      {
        source: '/api/auth/:path*',
        destination: '/api/auth/[...all]',
      },
    )
  })
})

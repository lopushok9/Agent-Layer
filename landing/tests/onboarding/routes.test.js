import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { PRERENDER_PATHS, resolveRoute } from '../../src/routes.js'

describe('onboarding route', () => {
  it('resolves and prerenders /onboard', () => {
    assert.deepEqual(resolveRoute({ pathname: '/onboard', hash: '' }), {
      page: 'onboard',
      path: '/onboard',
    })
    assert.equal(PRERENDER_PATHS.includes('/onboard'), true)
  })
})

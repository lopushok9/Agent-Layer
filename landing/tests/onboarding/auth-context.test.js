import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { selectSocialAccount } from '../../api/_lib/auth-context.js'
import { OnboardingError } from '../../api/_lib/invites.js'

describe('social identity selection', () => {
  const github = {
    providerId: 'github',
    accountId: '123',
    userId: 'user-1',
  }
  const twitter = {
    providerId: 'twitter',
    accountId: '456',
    userId: 'user-1',
  }

  it('accepts either GitHub or X without age/activity rules', () => {
    assert.equal(selectSocialAccount([github]).publicProvider, 'github')
    assert.equal(selectSocialAccount([twitter]).publicProvider, 'x')
  })

  it('normalizes Better Auth twitter to public provider x', () => {
    assert.equal(selectSocialAccount([twitter], 'x').providerId, 'twitter')
  })

  it('uses the explicitly requested provider when two are connected', () => {
    assert.equal(selectSocialAccount([github, twitter], 'github').accountId, '123')
    assert.equal(selectSocialAccount([github, twitter], 'x').accountId, '456')
  })

  it('rejects missing, unsupported, and ambiguous provider identities', () => {
    assert.throws(
      () => selectSocialAccount([]),
      (error) => error instanceof OnboardingError && error.code === 'provider_not_connected',
    )
    assert.throws(
      () => selectSocialAccount([{ providerId: 'linkedin', accountId: '1' }]),
      (error) => error instanceof OnboardingError && error.code === 'provider_not_connected',
    )
    assert.throws(
      () => selectSocialAccount([github, twitter]),
      (error) => error instanceof OnboardingError && error.code === 'provider_required',
    )
  })
})

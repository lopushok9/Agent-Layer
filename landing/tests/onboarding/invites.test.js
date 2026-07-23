import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import {
  bindInvite,
  OnboardingError,
  generateInviteCode,
  hashInviteCode,
  issueInvite,
  normalizeBaseAddress,
  resolveBindingState,
  validateInviteCode,
} from '../../api/_lib/invites.js'

const ADDRESS = '0x1111111111111111111111111111111111111111'
const OTHER_ADDRESS = '0x2222222222222222222222222222222222222222'

function scriptedDatabase(steps) {
  const calls = []
  let released = false
  const client = {
    async query(sql, parameters = []) {
      const normalizedSql = String(sql).replace(/\s+/g, ' ').trim()
      calls.push({ sql: normalizedSql, parameters })
      const step = steps.shift()
      assert.ok(step, `Unexpected query: ${normalizedSql}`)
      assert.match(normalizedSql, step.match)
      if (step.error) throw step.error
      return step.result ?? { rows: [] }
    },
    release() {
      released = true
    },
  }
  return {
    calls,
    get released() {
      return released
    },
    async connect() {
      return client
    },
  }
}

describe('invite codes', () => {
  it('generates a high-entropy, URL-safe code', () => {
    const code = generateInviteCode((length) => Buffer.alloc(length, 7))
    assert.match(code, /^alw_[A-Za-z0-9_-]{43}$/)
    assert.equal(validateInviteCode(code), code)
  })

  it('stores a deterministic SHA-256 hash instead of the raw code', () => {
    const code = generateInviteCode((length) => Buffer.alloc(length, 9))
    const digest = hashInviteCode(code)
    assert.match(digest, /^[0-9a-f]{64}$/)
    assert.equal(digest, hashInviteCode(code))
    assert.notEqual(digest, code)
  })

  it('rejects malformed codes', () => {
    assert.throws(
      () => validateInviteCode('alw_short'),
      (error) => error instanceof OnboardingError && error.code === 'invalid_invite',
    )
  })
})

describe('invite persistence', () => {
  const code = generateInviteCode((length) => Buffer.alloc(length, 4))

  it('issues the assessment and invite in one transaction', async () => {
    const database = scriptedDatabase([
      { match: /^BEGIN$/ },
      { match: /^INSERT INTO onboarding_assessments/, result: { rows: [{ id: 'assessment-1' }] } },
      { match: /^INSERT INTO onboarding_invites/, result: { rows: [{ id: 'invite-1' }] } },
      { match: /^COMMIT$/ },
    ])

    const result = await issueInvite({
      database,
      campaignId: 'welcome_base_v1',
      userId: 'user-1',
      provider: 'github',
      providerSubjectId: '12345',
      ttlSeconds: 60,
      now: new Date('2026-07-23T00:00:00.000Z'),
      code,
    })

    assert.equal(result.invite, code)
    assert.equal(result.expiresAt, '2026-07-23T00:01:00.000Z')
    assert.equal(database.released, true)
    const inviteInsert = database.calls.find((call) => call.sql.startsWith('INSERT INTO onboarding_invites'))
    assert.equal(inviteInsert.parameters.includes(code), false)
    assert.equal(inviteInsert.parameters.includes(hashInviteCode(code)), true)
  })

  it('binds using a locked invite row and commits once', async () => {
    const database = scriptedDatabase([
      { match: /^BEGIN$/ },
      {
        match: /^SELECT id, status, expires_at, base_address/,
        result: {
          rows: [{
            id: 'invite-1',
            status: 'issued',
            expires_at: '2026-07-24T00:00:00.000Z',
            base_address: null,
          }],
        },
      },
      { match: /^UPDATE onboarding_invites SET status = 'bound'/ },
      { match: /^COMMIT$/ },
    ])

    const result = await bindInvite({
      database,
      code,
      address: ADDRESS,
      campaignId: 'welcome_base_v1',
      now: new Date('2026-07-23T00:00:00.000Z'),
    })

    assert.deepEqual(result, {
      status: 'bound',
      network: 'base',
      address: ADDRESS,
    })
    assert.equal(database.released, true)
  })

  it('rolls back a failed binding transaction', async () => {
    const database = scriptedDatabase([
      { match: /^BEGIN$/ },
      { match: /^SELECT id, status, expires_at, base_address/, result: { rows: [] } },
      { match: /^ROLLBACK$/ },
    ])

    await assert.rejects(
      bindInvite({
        database,
        code,
        address: ADDRESS,
        campaignId: 'welcome_base_v1',
      }),
      (error) => error instanceof OnboardingError && error.code === 'invalid_invite',
    )
    assert.equal(database.released, true)
  })
})

describe('Base address normalization', () => {
  it('normalizes an EVM address for storage', () => {
    assert.deepEqual(normalizeBaseAddress(ADDRESS.toUpperCase().replace('0X', '0x')), {
      checksum: ADDRESS,
      storage: ADDRESS,
    })
  })

  it('rejects the zero address and malformed values', () => {
    assert.throws(
      () => normalizeBaseAddress('0x0000000000000000000000000000000000000000'),
      (error) => error instanceof OnboardingError && error.code === 'invalid_base_address',
    )
    assert.throws(() => normalizeBaseAddress('not-an-address'), OnboardingError)
  })
})

describe('binding state', () => {
  const future = '2030-01-01T00:00:00.000Z'
  const now = new Date('2026-07-23T00:00:00.000Z')
  const normalizedAddress = normalizeBaseAddress(ADDRESS)

  it('allows an issued invite to bind', () => {
    assert.deepEqual(
      resolveBindingState({ status: 'issued', expires_at: future }, normalizedAddress, now),
      { action: 'bind' },
    )
  })

  it('makes the same code and address idempotent', () => {
    assert.deepEqual(
      resolveBindingState(
        { status: 'bound', expires_at: future, base_address: ADDRESS },
        normalizedAddress,
        now,
      ),
      { action: 'already_bound' },
    )
  })

  it('rejects rebinding the same invite to another address', () => {
    assert.throws(
      () => resolveBindingState(
        { status: 'bound', expires_at: future, base_address: OTHER_ADDRESS },
        normalizedAddress,
        now,
      ),
      (error) => error instanceof OnboardingError && error.code === 'invite_already_bound',
    )
  })

  it('rejects expired and revoked invites', () => {
    assert.throws(
      () => resolveBindingState(
        { status: 'issued', expires_at: '2026-07-22T23:59:59.000Z' },
        normalizedAddress,
        now,
      ),
      (error) => error instanceof OnboardingError && error.code === 'invite_expired',
    )
    assert.throws(
      () => resolveBindingState(
        { status: 'revoked', expires_at: future },
        normalizedAddress,
        now,
      ),
      (error) => error instanceof OnboardingError && error.code === 'invite_revoked',
    )
  })
})

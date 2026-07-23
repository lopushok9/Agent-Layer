import { createHash, randomBytes } from 'node:crypto'

import { getAddress, isAddress, zeroAddress } from 'viem'

const INVITE_PREFIX = 'alw_'
const INVITE_SECRET_BYTES = 32
const INVITE_PATTERN = /^alw_[A-Za-z0-9_-]{43}$/

export class OnboardingError extends Error {
  constructor(code, status, message = code) {
    super(message)
    this.name = 'OnboardingError'
    this.code = code
    this.status = status
  }
}

export function generateInviteCode(bytes = randomBytes) {
  const secret = bytes(INVITE_SECRET_BYTES).toString('base64url')
  return `${INVITE_PREFIX}${secret}`
}

export function validateInviteCode(code) {
  const normalized = String(code || '').trim()
  if (!INVITE_PATTERN.test(normalized)) {
    throw new OnboardingError('invalid_invite', 401, 'Invite code is invalid.')
  }
  return normalized
}

export function hashInviteCode(code) {
  return createHash('sha256').update(validateInviteCode(code), 'utf8').digest('hex')
}

export function normalizeBaseAddress(address) {
  const value = String(address || '').trim()
  if (!isAddress(value, { strict: false })) {
    throw new OnboardingError('invalid_base_address', 400, 'Base address is invalid.')
  }

  const checksumAddress = getAddress(value)
  if (checksumAddress.toLowerCase() === zeroAddress) {
    throw new OnboardingError('invalid_base_address', 400, 'Base address cannot be the zero address.')
  }
  return {
    checksum: checksumAddress,
    storage: checksumAddress.toLowerCase(),
  }
}

export function resolveBindingState(invite, normalizedAddress, now = new Date()) {
  if (!invite) {
    throw new OnboardingError('invalid_invite', 401, 'Invite code is invalid.')
  }

  if (invite.status === 'bound') {
    if (String(invite.base_address || '').toLowerCase() === normalizedAddress.storage) {
      return { action: 'already_bound' }
    }
    throw new OnboardingError('invite_already_bound', 409, 'Invite is already bound to another address.')
  }

  if (invite.status === 'revoked') {
    throw new OnboardingError('invite_revoked', 410, 'Invite has been revoked.')
  }

  if (invite.status === 'expired' || new Date(invite.expires_at).getTime() <= now.getTime()) {
    throw new OnboardingError('invite_expired', 410, 'Invite has expired.')
  }

  if (invite.status !== 'issued') {
    throw new OnboardingError('invalid_invite', 401, 'Invite code is invalid.')
  }

  return { action: 'bind' }
}

async function runTransaction(database, callback) {
  const client = await database.connect()
  try {
    await client.query('BEGIN')
    const result = await callback(client)
    await client.query('COMMIT')
    return result
  } catch (error) {
    await client.query('ROLLBACK')
    throw error
  } finally {
    client.release()
  }
}

export async function issueInvite({
  database,
  campaignId,
  userId,
  provider,
  providerSubjectId,
  ttlSeconds,
  now = new Date(),
  code = generateInviteCode(),
}) {
  const expiresAt = new Date(now.getTime() + ttlSeconds * 1_000)
  const codeHash = hashInviteCode(code)

  return runTransaction(database, async (client) => {
    const assessment = await client.query(
      `
        INSERT INTO onboarding_assessments (
          campaign_id,
          user_id,
          provider,
          provider_subject_id,
          rules_version,
          decision,
          evaluated_at
        )
        VALUES ($1, $2, $3, $4, 'provider_identity_v1', 'eligible', $5)
        ON CONFLICT (campaign_id, provider, provider_subject_id)
        DO NOTHING
        RETURNING id
      `,
      [campaignId, userId, provider, providerSubjectId, now],
    )

    let assessmentId = assessment.rows[0]?.id
    if (!assessmentId) {
      const existingAssessment = await client.query(
        `
          SELECT id, user_id
          FROM onboarding_assessments
          WHERE campaign_id = $1
            AND provider = $2
            AND provider_subject_id = $3
        `,
        [campaignId, provider, providerSubjectId],
      )
      const row = existingAssessment.rows[0]
      if (!row || row.user_id !== userId) {
        throw new OnboardingError('already_claimed', 409, 'This social account already claimed an invite.')
      }
      assessmentId = row.id
    }

    const inserted = await client.query(
      `
        INSERT INTO onboarding_invites (
          campaign_id,
          user_id,
          assessment_id,
          code_hash,
          status,
          expires_at,
          created_at
        )
        VALUES ($1, $2, $3, $4, 'issued', $5, $6)
        ON CONFLICT (campaign_id, user_id)
        DO NOTHING
        RETURNING id
      `,
      [campaignId, userId, assessmentId, codeHash, expiresAt, now],
    )

    if (!inserted.rows[0]) {
      throw new OnboardingError(
        'already_claimed',
        409,
        'An invite already exists. Replace it from the onboarding page if it was lost.',
      )
    }

    return {
      invite: code,
      expiresAt: expiresAt.toISOString(),
    }
  })
}

export async function replaceInvite({
  database,
  campaignId,
  userId,
  ttlSeconds,
  now = new Date(),
  code = generateInviteCode(),
}) {
  const expiresAt = new Date(now.getTime() + ttlSeconds * 1_000)
  const codeHash = hashInviteCode(code)
  const result = await database.query(
    `
      UPDATE onboarding_invites
      SET code_hash = $1,
          status = 'issued',
          expires_at = $2
      WHERE campaign_id = $3
        AND user_id = $4
        AND status IN ('issued', 'expired')
      RETURNING id
    `,
    [codeHash, expiresAt, campaignId, userId],
  )

  if (!result.rows[0]) {
    throw new OnboardingError('invite_not_replaceable', 409, 'Invite cannot be replaced.')
  }

  return {
    invite: code,
    expiresAt: expiresAt.toISOString(),
  }
}

export async function bindInvite({
  database,
  code,
  address,
  campaignId,
  now = new Date(),
}) {
  const codeHash = hashInviteCode(code)
  const normalizedAddress = normalizeBaseAddress(address)

  try {
    return await runTransaction(database, async (client) => {
      const inviteResult = await client.query(
        `
          SELECT id, status, expires_at, base_address
          FROM onboarding_invites
          WHERE campaign_id = $1
            AND code_hash = $2
          FOR UPDATE
        `,
        [campaignId, codeHash],
      )
      const invite = inviteResult.rows[0]
      const binding = resolveBindingState(invite, normalizedAddress, now)

      if (binding.action === 'already_bound') {
        return {
          status: 'already_bound',
          network: 'base',
          address: normalizedAddress.checksum,
        }
      }

      await client.query(
        `
          UPDATE onboarding_invites
          SET status = 'bound',
              base_address = $1,
              bound_at = $2
          WHERE id = $3
        `,
        [normalizedAddress.storage, now, invite.id],
      )
      return {
        status: 'bound',
        network: 'base',
        address: normalizedAddress.checksum,
      }
    })
  } catch (error) {
    if (error?.code === '23505') {
      throw new OnboardingError('address_already_used', 409, 'Base address was already used.')
    }
    throw error
  }
}

export function bearerInvite(authorizationHeader) {
  const match = /^Bearer\s+(.+)$/i.exec(String(authorizationHeader || '').trim())
  if (!match) {
    throw new OnboardingError('invalid_invite', 401, 'Invite code is required.')
  }
  return validateInviteCode(match[1])
}

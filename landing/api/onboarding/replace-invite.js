import { authenticatedContext } from '../_lib/auth-context.js'
import { onboardingConfig } from '../_lib/config.js'
import { getPool } from '../_lib/db.js'
import { methodNotAllowed, requestJson, sendApiError, sendJson } from '../_lib/http.js'
import { replaceInvite } from '../_lib/invites.js'

export default async function replaceInviteHandler(req, res) {
  if (req.method !== 'POST') return methodNotAllowed(res)
  try {
    const body = requestJson(req)
    const { campaignId, inviteTtlSeconds } = onboardingConfig()
    const { session } = await authenticatedContext(req, body.provider)
    const result = await replaceInvite({
      database: getPool(),
      campaignId,
      userId: session.user.id,
      ttlSeconds: inviteTtlSeconds,
    })
    return sendJson(res, 200, {
      ok: true,
      invite: result.invite,
      expiresAt: result.expiresAt,
    })
  } catch (error) {
    return sendApiError(res, error)
  }
}

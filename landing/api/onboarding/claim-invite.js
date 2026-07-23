import { authenticatedContext } from '../_lib/auth-context.js'
import { onboardingConfig } from '../_lib/config.js'
import { getPool } from '../_lib/db.js'
import { methodNotAllowed, requestJson, sendApiError, sendJson } from '../_lib/http.js'
import { issueInvite } from '../_lib/invites.js'

export default async function claimInviteHandler(req, res) {
  if (req.method !== 'POST') return methodNotAllowed(res)
  try {
    const body = requestJson(req)
    const { campaignId, inviteTtlSeconds } = onboardingConfig()
    const { session, socialAccount } = await authenticatedContext(req, body.provider)
    const result = await issueInvite({
      database: getPool(),
      campaignId,
      userId: session.user.id,
      provider: socialAccount.publicProvider,
      providerSubjectId: socialAccount.accountId,
      ttlSeconds: inviteTtlSeconds,
    })
    return sendJson(res, 201, {
      ok: true,
      eligible: true,
      provider: socialAccount.publicProvider,
      invite: result.invite,
      expiresAt: result.expiresAt,
    })
  } catch (error) {
    return sendApiError(res, error)
  }
}

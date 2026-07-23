import { onboardingConfig } from '../_lib/config.js'
import { getPool } from '../_lib/db.js'
import { methodNotAllowed, requestJson, sendApiError, sendJson } from '../_lib/http.js'
import { bearerInvite, bindInvite } from '../_lib/invites.js'

export default async function bindWalletHandler(req, res) {
  if (req.method !== 'POST') return methodNotAllowed(res)
  try {
    const body = requestJson(req)
    const code = bearerInvite(req.headers.authorization)
    const { campaignId } = onboardingConfig()
    const result = await bindInvite({
      database: getPool(),
      campaignId,
      code,
      address: body.address,
    })
    return sendJson(res, 200, {
      ok: true,
      ...result,
    })
  } catch (error) {
    return sendApiError(res, error)
  }
}

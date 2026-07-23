import { optionalSession } from '../_lib/auth-context.js'
import { methodNotAllowed, sendApiError, sendJson } from '../_lib/http.js'

export default async function sessionHandler(req, res) {
  if (req.method !== 'GET') return methodNotAllowed(res, ['GET'])
  try {
    const context = await optionalSession(req)
    return sendJson(res, 200, {
      ok: true,
      authenticated: Boolean(context.session),
      user: context.session
        ? {
            id: context.session.user.id,
            name: context.session.user.name,
            image: context.session.user.image || null,
          }
        : null,
      providers: [...new Set(context.providers)],
    })
  } catch (error) {
    return sendApiError(res, error)
  }
}

import { configuredAuthProviders } from '../_lib/auth.js'
import { methodNotAllowed, sendJson } from '../_lib/http.js'

export default function providersHandler(req, res) {
  if (req.method !== 'GET') return methodNotAllowed(res, ['GET'])
  return sendJson(res, 200, {
    ok: true,
    providers: configuredAuthProviders(),
  })
}

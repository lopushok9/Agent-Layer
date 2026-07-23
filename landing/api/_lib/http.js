import { OnboardingError } from './invites.js'

export function setNoStore(res) {
  res.setHeader('Cache-Control', 'no-store')
  res.setHeader('Content-Type', 'application/json; charset=utf-8')
  res.setHeader('X-Content-Type-Options', 'nosniff')
}

export function sendJson(res, status, payload) {
  setNoStore(res)
  return res.status(status).json(payload)
}

export function requestJson(req, maxBytes = 4_096) {
  const contentLength = Number.parseInt(String(req.headers?.['content-length'] || '0'), 10)
  if (Number.isFinite(contentLength) && contentLength > maxBytes) {
    throw new OnboardingError('request_too_large', 413, 'Request body is too large.')
  }

  if (req.body === undefined || req.body === null || req.body === '') return {}
  if (typeof req.body === 'object' && !Buffer.isBuffer(req.body)) return req.body
  try {
    return JSON.parse(Buffer.from(req.body).toString('utf8'))
  } catch {
    throw new OnboardingError('invalid_json', 400, 'Request body must be valid JSON.')
  }
}

export function methodNotAllowed(res, allowed = ['POST']) {
  res.setHeader('Allow', allowed.join(', '))
  return sendJson(res, 405, { ok: false, error: 'method_not_allowed' })
}

export function sendApiError(res, error) {
  if (error instanceof OnboardingError) {
    return sendJson(res, error.status, {
      ok: false,
      error: error.code,
      message: error.message,
    })
  }

  console.error('onboarding_api_error', {
    name: error?.name || 'Error',
    message: error?.message || 'Unknown onboarding API error',
  })
  return sendJson(res, 500, {
    ok: false,
    error: 'internal_error',
    message: 'The onboarding service is temporarily unavailable.',
  })
}

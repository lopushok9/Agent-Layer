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

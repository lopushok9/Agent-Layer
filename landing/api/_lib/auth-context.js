import { fromNodeHeaders } from 'better-auth/node'

import { getAuth } from './auth.js'
import { normalizeSocialProvider } from './config.js'
import { OnboardingError } from './invites.js'

export function selectSocialAccount(accounts, requestedProvider = null) {
  const supported = accounts
    .map((account) => ({
      ...account,
      publicProvider: normalizeSocialProvider(account.providerId),
    }))
    .filter((account) => account.publicProvider && account.accountId)

  if (requestedProvider) {
    const normalizedRequested = normalizeSocialProvider(requestedProvider)
    const selected = supported.find((account) => account.publicProvider === normalizedRequested)
    if (!selected) {
      throw new OnboardingError('provider_not_connected', 400, 'Selected social account is not connected.')
    }
    return selected
  }

  if (supported.length === 1) return supported[0]
  if (supported.length === 0) {
    throw new OnboardingError('provider_not_connected', 400, 'Connect GitHub or X first.')
  }
  throw new OnboardingError('provider_required', 400, 'Choose GitHub or X for this claim.')
}

export async function authenticatedContext(req, requestedProvider = null, auth = getAuth()) {
  const headers = fromNodeHeaders(req.headers)
  const session = await auth.api.getSession({ headers })
  if (!session?.user?.id) {
    throw new OnboardingError('authentication_required', 401, 'Sign in with GitHub or X first.')
  }

  const accounts = await auth.api.listUserAccounts({ headers })
  const socialAccount = selectSocialAccount(accounts, requestedProvider)
  return {
    session,
    socialAccount,
  }
}

export async function optionalSession(req, auth = getAuth()) {
  const headers = fromNodeHeaders(req.headers)
  const session = await auth.api.getSession({ headers })
  if (!session?.user?.id) {
    return { session: null, providers: [] }
  }
  const accounts = await auth.api.listUserAccounts({ headers })
  return {
    session,
    providers: accounts
      .map((account) => normalizeSocialProvider(account.providerId))
      .filter(Boolean),
  }
}

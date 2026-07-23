import { betterAuth } from 'better-auth'

import { getPool } from './db.js'

let authInstance

function requiredSecret(env) {
  const secret = String(env.BETTER_AUTH_SECRET || '').trim()
  if (secret.length < 32) {
    throw new Error('BETTER_AUTH_SECRET must contain at least 32 characters.')
  }
  return secret
}

function authBaseUrl(env) {
  const baseUrl = String(env.BETTER_AUTH_URL || '').trim().replace(/\/+$/, '')
  if (!baseUrl) {
    throw new Error('BETTER_AUTH_URL is required.')
  }
  return baseUrl
}

export function configuredAuthProviders(env = process.env) {
  const providers = []
  if (env.GITHUB_CLIENT_ID && env.GITHUB_CLIENT_SECRET) providers.push('github')
  if (env.X_CLIENT_ID && env.X_CLIENT_SECRET) providers.push('x')
  return providers
}

function socialProviders(env) {
  const providers = {}
  if (env.GITHUB_CLIENT_ID && env.GITHUB_CLIENT_SECRET) {
    providers.github = {
      clientId: env.GITHUB_CLIENT_ID,
      clientSecret: env.GITHUB_CLIENT_SECRET,
    }
  }
  if (env.X_CLIENT_ID && env.X_CLIENT_SECRET) {
    providers.twitter = {
      clientId: env.X_CLIENT_ID,
      clientSecret: env.X_CLIENT_SECRET,
    }
  }
  return providers
}

function trustedOrigins(env, baseUrl) {
  const extra = String(env.ONBOARDING_TRUSTED_ORIGINS || '')
    .split(',')
    .map((origin) => origin.trim())
    .filter(Boolean)
  return [...new Set([baseUrl, ...extra])]
}

export function createAuth(env = process.env) {
  const baseURL = authBaseUrl(env)
  return betterAuth({
    appName: 'AgentLayer',
    baseURL,
    secret: requiredSecret(env),
    database: getPool(env),
    trustedOrigins: trustedOrigins(env, baseURL),
    socialProviders: socialProviders(env),
    emailAndPassword: {
      enabled: false,
    },
    account: {
      encryptOAuthTokens: true,
      accountLinking: {
        enabled: true,
        disableImplicitLinking: true,
        allowDifferentEmails: false,
      },
    },
    advanced: {
      useSecureCookies: baseURL.startsWith('https://'),
    },
  })
}

export function getAuth(env = process.env) {
  if (!authInstance) authInstance = createAuth(env)
  return authInstance
}

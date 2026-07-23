const DEFAULT_CAMPAIGN_ID = 'welcome_base_v1'
const DEFAULT_INVITE_TTL_SECONDS = 7 * 24 * 60 * 60
const MAX_INVITE_TTL_SECONDS = 30 * 24 * 60 * 60

function positiveInteger(value, fallback) {
  const parsed = Number.parseInt(String(value ?? ''), 10)
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : fallback
}

export function onboardingConfig(env = process.env) {
  return {
    campaignId: String(env.ONBOARDING_CAMPAIGN_ID || DEFAULT_CAMPAIGN_ID).trim(),
    inviteTtlSeconds: Math.min(
      positiveInteger(env.ONBOARDING_INVITE_TTL_SECONDS, DEFAULT_INVITE_TTL_SECONDS),
      MAX_INVITE_TTL_SECONDS,
    ),
  }
}

export function requireDatabaseUrl(env = process.env) {
  const databaseUrl = String(env.DATABASE_URL || '').trim()
  if (!databaseUrl) {
    throw new Error('DATABASE_URL is required for onboarding API requests.')
  }
  return databaseUrl
}

export const SUPPORTED_SOCIAL_PROVIDERS = new Set(['github', 'x'])

export function normalizeSocialProvider(provider) {
  const normalized = String(provider || '').trim().toLowerCase()
  if (normalized === 'twitter') return 'x'
  if (SUPPORTED_SOCIAL_PROVIDERS.has(normalized)) return normalized
  return null
}

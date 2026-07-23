import { useEffect, useMemo, useState } from 'react'

import { authClient } from '../auth-client'
import '../styles/OnboardingPage.css'

const PROVIDER_LABELS = {
  github: 'GitHub',
  x: 'X',
}

async function onboardingRequest(path, options = {}) {
  const response = await fetch(path, {
    credentials: 'same-origin',
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
    ...options,
  })
  const payload = await response.json()
  if (!response.ok) {
    const error = new Error(payload.message || 'Onboarding request failed.')
    error.code = payload.error
    error.status = response.status
    throw error
  }
  return payload
}

function providerFromUrl() {
  if (typeof window === 'undefined') return null
  const provider = new URLSearchParams(window.location.search).get('provider')
  return provider === 'github' || provider === 'x' ? provider : null
}

function authErrorFromUrl() {
  if (typeof window === 'undefined') return null
  const params = new URLSearchParams(window.location.search)
  if (!params.has('error') && !params.has('auth_error')) return null
  return 'Social sign-in was not completed. Please try again.'
}

export function OnboardingPage() {
  const [availableProviders, setAvailableProviders] = useState([])
  const [session, setSession] = useState(null)
  const [selectedProvider, setSelectedProvider] = useState(providerFromUrl)
  const [loading, setLoading] = useState(true)
  const [working, setWorking] = useState(false)
  const [invite, setInvite] = useState(null)
  const [error, setError] = useState(authErrorFromUrl)
  const [canReplace, setCanReplace] = useState(false)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    let active = true
    Promise.all([
      onboardingRequest('/api/onboarding/providers'),
      onboardingRequest('/api/onboarding/session'),
    ])
      .then(([providersPayload, sessionPayload]) => {
        if (!active) return
        setAvailableProviders(providersPayload.providers || [])
        setSession(sessionPayload)
        if (!selectedProvider && sessionPayload.providers?.length === 1) {
          setSelectedProvider(sessionPayload.providers[0])
        }
      })
      .catch((requestError) => {
        if (active) setError(requestError.message)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [selectedProvider])

  const command = useMemo(
    () => invite
      ? `npx @agentlayer.tech/wallet install --yes --invite ${invite.code}`
      : '',
    [invite],
  )

  async function signIn(provider) {
    setWorking(true)
    setError(null)
    setSelectedProvider(provider)
    try {
      const authProvider = provider === 'x' ? 'twitter' : provider
      const result = await authClient.signIn.social({
        provider: authProvider,
        callbackURL: `/onboard?provider=${provider}`,
        errorCallbackURL: '/onboard?auth_error=1',
      })
      if (result?.error) {
        setError(result.error.message || `Could not connect ${PROVIDER_LABELS[provider]}.`)
        setWorking(false)
      }
    } catch (signInError) {
      setError(signInError.message || `Could not connect ${PROVIDER_LABELS[provider]}.`)
      setWorking(false)
    }
  }

  async function createInvite({ replace = false } = {}) {
    if (!selectedProvider) {
      setError('Choose GitHub or X first.')
      return
    }
    setWorking(true)
    setError(null)
    setCopied(false)
    try {
      const payload = await onboardingRequest(
        replace
          ? '/api/onboarding/replace-invite'
          : '/api/onboarding/claim-invite',
        {
          method: 'POST',
          body: JSON.stringify({ provider: selectedProvider }),
        },
      )
      setInvite({
        code: payload.invite,
        expiresAt: payload.expiresAt,
      })
      setCanReplace(false)
    } catch (requestError) {
      if (requestError.code === 'already_claimed') setCanReplace(true)
      setError(requestError.message)
    } finally {
      setWorking(false)
    }
  }

  async function copyCommand() {
    try {
      await navigator.clipboard.writeText(command)
      setCopied(true)
    } catch {
      setError('Could not copy automatically. Select and copy the command manually.')
    }
  }

  async function signOut() {
    setWorking(true)
    try {
      await authClient.signOut()
      setSession(null)
      setSelectedProvider(null)
      setInvite(null)
      setCanReplace(false)
    } catch (signOutError) {
      setError(signOutError.message || 'Could not sign out.')
    } finally {
      setWorking(false)
    }
  }

  const connectedProviders = session?.providers || []
  const connected = selectedProvider && connectedProviders.includes(selectedProvider)

  return (
    <div className="ob-page">
      <header className="ob-header">
        <a href="/" className="ob-brand">
          <img src="/apple-touch-icon.png" alt="AgentLayer logo" className="ob-brand-mark" />
          <span className="wordmark-lockup">
            <span className="ob-brand-text">AgentLayer</span>
            <span className="wordmark-beta" aria-hidden="true">β</span>
          </span>
        </a>
        <a href="/wallet" className="ob-back-link">Wallet</a>
      </header>

      <main className="ob-main">
        <section className="ob-intro">
          <span className="ob-kicker">Base welcome credit</span>
          <h1>Start your agent<br />with $1.</h1>
          <p>
            Connect GitHub or X, create your AgentLayer wallet, and use the
            welcome credit for x402 payments on Base.
          </p>
          <div className="ob-facts" aria-label="Campaign details">
            <span>GitHub or X</span>
            <span>One-time invite</span>
            <span>Base network</span>
          </div>
        </section>

        <section className="ob-panel" aria-live="polite">
          <div className="ob-step">
            <span className="ob-step-number">01</span>
            <div>
              <h2>Verify one account</h2>
              <p>Choose either provider. You do not need to connect both.</p>
            </div>
          </div>

          {loading ? (
            <div className="ob-loading">Checking onboarding availability…</div>
          ) : (
            <div className="ob-provider-grid">
              {Object.keys(PROVIDER_LABELS).map((provider) => {
                const enabled = availableProviders.includes(provider)
                const isConnected = connectedProviders.includes(provider)
                return (
                  <button
                    className={`ob-provider-button${isConnected ? ' ob-provider-connected' : ''}`}
                    disabled={working || (!enabled && !isConnected)}
                    key={provider}
                    onClick={() => {
                      if (isConnected) {
                        setSelectedProvider(provider)
                        setError(null)
                      } else {
                        signIn(provider)
                      }
                    }}
                    type="button"
                  >
                    <span>{isConnected ? 'Connected' : 'Continue with'}</span>
                    <strong>{PROVIDER_LABELS[provider]}</strong>
                    {!enabled && <small>Not configured</small>}
                  </button>
                )
              })}
            </div>
          )}

          {session?.authenticated && (
            <div className="ob-session-row">
              <span>Signed in as {session.user?.name || 'AgentLayer user'}</span>
              <button type="button" onClick={signOut} disabled={working}>Sign out</button>
            </div>
          )}

          <div className="ob-divider" />

          <div className="ob-step">
            <span className="ob-step-number">02</span>
            <div>
              <h2>Create your invite</h2>
              <p>The raw code is shown once and is never retained in the database.</p>
            </div>
          </div>

          {!invite && (
            <div className="ob-claim-row">
              <button
                className="ob-primary-button"
                disabled={!connected || working}
                onClick={() => createInvite()}
                type="button"
              >
                {working ? 'Working…' : 'Create invite code'}
              </button>
              {canReplace && (
                <button
                  className="ob-secondary-button"
                  disabled={working}
                  onClick={() => createInvite({ replace: true })}
                  type="button"
                >
                  Replace lost code
                </button>
              )}
            </div>
          )}

          {invite && (
            <div className="ob-invite-result">
              <div className="ob-command-label">
                <span>Run in your terminal</span>
                <span>Expires {new Date(invite.expiresAt).toLocaleDateString()}</span>
              </div>
              <code>{command}</code>
              <button className="ob-primary-button" type="button" onClick={copyCommand}>
                {copied ? 'Copied' : 'Copy install command'}
              </button>
              <p className="ob-security-note">
                Keep this command private. The invite is consumed only after the
                installer binds it to your local Base address.
              </p>
            </div>
          )}

          {error && <div className="ob-error" role="alert">{error}</div>}
        </section>
      </main>
    </div>
  )
}

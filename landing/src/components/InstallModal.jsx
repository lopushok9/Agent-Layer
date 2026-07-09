import { useEffect, useState } from 'react'
import '../styles/InstallModal.css'

const OPENCLAW_INSTALL = 'npx @agentlayer.tech/wallet install --yes'
const HERMES_INSTALL =
  'npx @agentlayer.tech/wallet install --yes && npx @agentlayer.tech/wallet hermes install --yes'

export const InstallModal = ({ isOpen, onClose }) => {
  const [copiedKey, setCopiedKey] = useState(null)

  useEffect(() => {
    if (!isOpen) return undefined

    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    const onKeyDown = (event) => {
      if (event.key === 'Escape') onClose()
    }

    window.addEventListener('keydown', onKeyDown)

    return () => {
      document.body.style.overflow = previousOverflow
      window.removeEventListener('keydown', onKeyDown)
    }
  }, [isOpen, onClose])

  const handleCopy = async (value, key) => {
    try {
      await navigator.clipboard.writeText(value)
      setCopiedKey(key)
      window.setTimeout(() => {
        setCopiedKey((currentKey) => (currentKey === key ? null : currentKey))
      }, 1600)
    } catch {
      setCopiedKey(null)
    }
  }

  if (!isOpen) return null

  return (
    <div className="install-modal-overlay" onClick={onClose} role="presentation">
      <section
        className="install-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="install-modal-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="install-modal-header">
          <div>
            <span className="install-modal-eyebrow">Beta</span>
            <h2 id="install-modal-title" className="install-modal-title">Install AgentLayer</h2>
          </div>
          <button type="button" className="install-modal-close" onClick={onClose} aria-label="Close install dialog">
            Close
          </button>
        </div>

        <div className="install-modal-body">
          <p className="install-modal-copy">
            Beta release. Use the default install for OpenClaw, or add Hermes in the same step.
          </p>

          <div className="install-modal-stack">
            <section className="install-modal-panel" aria-label="OpenClaw install command">
              <div className="install-modal-panel-head">
                <div>
                  <span className="install-modal-code-label">OpenClaw</span>
                  <h3 className="install-modal-panel-title">Default install</h3>
                </div>
                <button
                  type="button"
                  className="install-modal-copy-btn"
                  onClick={() => handleCopy(OPENCLAW_INSTALL, 'openclaw')}
                  aria-label="Copy OpenClaw install command"
                >
                  {copiedKey === 'openclaw' ? 'Copied' : 'Copy'}
                </button>
              </div>

              <pre className="install-modal-code">
                <code>{OPENCLAW_INSTALL}</code>
              </pre>
            </section>

            <section className="install-modal-panel" aria-label="Hermes install command">
              <div className="install-modal-panel-head">
                <div>
                  <span className="install-modal-code-label">Hermes</span>
                  <h3 className="install-modal-panel-title">Install with Hermes</h3>
                </div>
                <button
                  type="button"
                  className="install-modal-copy-btn"
                  onClick={() => handleCopy(HERMES_INSTALL, 'hermes')}
                  aria-label="Copy Hermes install command"
                >
                  {copiedKey === 'hermes' ? 'Copied' : 'Copy'}
                </button>
              </div>

              <pre className="install-modal-code">
                <code>{HERMES_INSTALL}</code>
              </pre>
            </section>
          </div>
        </div>

        <div className="install-modal-footer">
          <p className="install-modal-note">
            Beta version. Test critical flows before relying on them in production.
          </p>
        </div>
      </section>
    </div>
  )
}

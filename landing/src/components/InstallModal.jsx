import { useEffect, useState } from 'react'
import '../styles/InstallModal.css'

const INSTALL_COMMAND = 'npx --yes @agentlayer.tech/wallet@latest install'
const SKILL_URL = 'https://www.agent-layer.tech/skill.md'

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
            Use this command to install AgentLayer into every detected framework.
          </p>

          <div className="install-modal-row">
            <pre className="install-modal-code">
              <code>{INSTALL_COMMAND}</code>
            </pre>
            <button
              type="button"
              className="install-modal-copy-btn"
              onClick={() => handleCopy(INSTALL_COMMAND, 'command')}
              aria-label="Copy install command"
            >
              {copiedKey === 'command' ? 'Copied' : 'Copy'}
            </button>
          </div>

          <p className="install-modal-copy install-modal-alt">
            Or give your agent this link.
          </p>

          <div className="install-modal-row">
            <a className="install-modal-link" href={SKILL_URL} target="_blank" rel="noreferrer">
              {SKILL_URL}
            </a>
            <button
              type="button"
              className="install-modal-copy-btn"
              onClick={() => handleCopy(SKILL_URL, 'link')}
              aria-label="Copy skill.md link"
            >
              {copiedKey === 'link' ? 'Copied' : 'Copy'}
            </button>
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

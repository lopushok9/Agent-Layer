import { useEffect, useState } from 'react'
import '../styles/InstallModal.css'

const MCP_CONFIG = `{
  "mcpServers": {
    "AgentLayer": {
      "url": "https://agent-layer-production-852f.up.railway.app/mcp"
    }
  }
}`

export const InstallModal = ({ isOpen, onClose }) => {
  const [copied, setCopied] = useState(false)

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

  useEffect(() => {
    if (!isOpen) {
      setCopied(false)
    }
  }, [isOpen])

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(MCP_CONFIG)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1600)
    } catch {
      setCopied(false)
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
            <span className="install-modal-eyebrow">Install</span>
            <h2 id="install-modal-title" className="install-modal-title">Connect AgentLayer</h2>
          </div>
          <button type="button" className="install-modal-close" onClick={onClose} aria-label="Close install dialog">
            Close
          </button>
        </div>

        <p className="install-modal-copy">
          Add this MCP server to your client config, or simply ask your OpenClaw agent to connect to the server directly.
        </p>

        <div className="install-modal-code-wrap">
          <div className="install-modal-code-top">
            <span className="install-modal-code-label">Server config</span>
            <button
              type="button"
              className="install-modal-copy-btn"
              onClick={handleCopy}
              aria-label="Copy MCP config"
            >
              {copied ? 'Copied' : 'Copy'}
            </button>
          </div>

          <pre className="install-modal-code">
            <code>{MCP_CONFIG}</code>
          </pre>
        </div>

        <div className="install-modal-footer">
          <p className="install-modal-note">
            Need more detail about setup and the project structure?
          </p>
          <a
            href="https://github.com/lopushok9/Agent-Layer"
            className="install-modal-link"
            target="_blank"
            rel="noreferrer"
          >
            View GitHub repository
          </a>
        </div>
      </section>
    </div>
  )
}

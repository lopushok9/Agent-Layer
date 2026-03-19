import { useEffect, useState } from 'react'
import '../styles/InstallModal.css'

const MCP_CONFIG = `{
  "mcpServers": {
    "AgentLayer": {
      "url": "https://agent-layer-production-852f.up.railway.app/mcp"
    }
  }
}`

const WALLET_INSTALL = `git clone https://github.com/lopushok9/Agent-Layer.git
cd Agent-Layer/agent-wallet
python3 scripts/install_agent_wallet.py`

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

  useEffect(() => {
    if (!isOpen) {
      setCopiedKey(null)
    }
  }, [isOpen])

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
            <span className="install-modal-eyebrow">Install</span>
            <h2 id="install-modal-title" className="install-modal-title">Connect AgentLayer</h2>
          </div>
          <button type="button" className="install-modal-close" onClick={onClose} aria-label="Close install dialog">
            Close
          </button>
        </div>

        <p className="install-modal-copy">
          Connect the AgentLayer MCP server first, then optionally install the local wallet runtime if you want balances, swaps, staking and approval-based execution inside OpenClaw.
        </p>

        <div className="install-modal-grid">
          <div className="install-modal-code-wrap">
            <div className="install-modal-code-top">
              <span className="install-modal-code-label">Step 01 · MCP server</span>
              <button
                type="button"
                className="install-modal-copy-btn"
                onClick={() => handleCopy(MCP_CONFIG, 'mcp')}
                aria-label="Copy MCP config"
              >
                {copiedKey === 'mcp' ? 'Copied' : 'Copy'}
              </button>
            </div>

            <pre className="install-modal-code">
              <code>{MCP_CONFIG}</code>
            </pre>

            <p className="install-modal-panel-note">
              Add this config to your client, or ask your OpenClaw agent to connect to the MCP endpoint directly.
            </p>
          </div>

          <div className="install-modal-code-wrap">
            <div className="install-modal-code-top">
              <span className="install-modal-code-label">Step 02 · Wallet runtime</span>
              <button
                type="button"
                className="install-modal-copy-btn"
                onClick={() => handleCopy(WALLET_INSTALL, 'wallet')}
                aria-label="Copy wallet install commands"
              >
                {copiedKey === 'wallet' ? 'Copied' : 'Copy'}
              </button>
            </div>

            <pre className="install-modal-code">
              <code>{WALLET_INSTALL}</code>
            </pre>

            <div className="install-modal-steps" aria-label="Wallet install notes">
              <p className="install-modal-panel-note">
                The installer creates local config, prepares the Python runtime, and patches OpenClaw for the wallet plugin.
              </p>
              <p className="install-modal-panel-note">
                For signing flows, provide <code>AGENT_WALLET_BOOT_KEY</code> and seal runtime secrets locally instead of storing them in config JSON.
              </p>
            </div>
          </div>
        </div>

        <div className="install-modal-footer">
          <p className="install-modal-note">
            Need more detail about setup, wallet runtime, or project structure?
          </p>
          <div className="install-modal-actions">
            <a
              href="https://github.com/lopushok9/Agent-Layer/tree/main/agent-wallet"
              className="install-modal-link install-modal-link-secondary"
              target="_blank"
              rel="noreferrer"
            >
              Wallet docs
            </a>
            <a
              href="https://github.com/lopushok9/Agent-Layer"
              className="install-modal-link"
              target="_blank"
              rel="noreferrer"
            >
              View GitHub repository
            </a>
          </div>
        </div>
      </section>
    </div>
  )
}

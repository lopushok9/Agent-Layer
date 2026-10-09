import express from "express";
import type { Config } from "./config.js";
import { html, secureHtml } from "./oauth.js";
import { randomToken } from "./security.js";

// Public landing page. Static and read-only: it never touches the database or
// a session, so it cannot affect the MCP, OAuth or payment routes.
const LOGO_URL = "https://www.agent-layer.tech/android-chrome-512x512.png";

export function homeRouter(config: Config) {
  const router = express.Router();
  router.get("/", (_req, res) => {
    const nonce = randomToken(16);
    secureHtml(res, nonce, "'none'").send(homePage(config.resource, Boolean(config.link), nonce));
  });
  return router;
}

export function homePage(mcpUrl: string, link: boolean, nonce: string) {
  const features = [
    "Pay x402 APIs with USDC on Base",
    "Send and receive USDC on Arc",
    ...(link ? ["Purchases from your own Link wallet, approved by you"] : []),
  ];
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light"><title>AgentLayer x402</title><meta name="description" content="A hosted wallet that lets AI agents pay for APIs and make purchases you approve."><link rel="icon" href="${LOGO_URL}"><style>${STYLES}</style></head><body>
<header><a class="brand" href="https://www.agent-layer.tech" rel="noopener"><img src="${LOGO_URL}" alt="" width="22" height="22"><span>Powered by AgentLayer</span></a><a class="signin" href="/muse">Connect Muse</a></header>
<main>
<h1>A wallet for your AI agent.</h1>
<p class="lead">Connect any MCP client to let your agent pay for APIs and make purchases on your behalf.</p>
<ol class="steps">
<li><span>Copy the MCP server URL.</span><div class="endpoint"><code id="mcp">${html(mcpUrl)}</code><button type="button" id="copy">Copy</button></div></li>
<li><span>In your agent's settings, open <strong>Connectors</strong> and add it as a custom connector.</span></li>
<li><span>Sign in with Google or GitHub when asked, and allow access.</span></li>
</ol>
<ul>${features.map((f) => `<li>${html(f)}</li>`).join("")}</ul>
</main>
<footer><a href="https://www.agent-layer.tech" rel="noopener">agent-layer.tech</a></footer>
<script nonce="${nonce}">document.getElementById("copy").addEventListener("click",function(){var b=this;navigator.clipboard.writeText(document.getElementById("mcp").textContent).then(function(){b.textContent="Copied";setTimeout(function(){b.textContent="Copy";},1600);});});</script>
</body></html>`;
}

const STYLES = `*{box-sizing:border-box}html,body{margin:0;background:#fff;color:#000}body{min-height:100vh;display:flex;flex-direction:column;font-family:Inter,ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-size:15px;line-height:1.5;-webkit-font-smoothing:antialiased}a{color:#000;text-decoration:none}header{display:flex;align-items:center;justify-content:space-between;padding:24px 32px}.brand{display:flex;align-items:center;gap:9px;font-size:13px;font-weight:600;letter-spacing:-.01em}.brand img{display:block;border-radius:5px}.signin{padding:8px 16px;border:1px solid #000;border-radius:999px;font-size:13px;font-weight:600}.signin:hover{background:#000;color:#fff}main{flex:1;width:100%;max-width:640px;margin:0 auto;padding:12vh 32px 64px}h1{margin:0;font-size:44px;line-height:1.08;font-weight:650;letter-spacing:-.04em}.lead{margin:20px 0 36px;color:#555;font-size:17px}.steps{margin:0;padding:0;list-style:none;counter-reset:step}.steps>li{position:relative;padding:0 0 22px 36px;counter-increment:step}.steps>li:before{content:counter(step);position:absolute;left:0;top:0;width:22px;height:22px;border:1px solid #000;border-radius:50%;font-size:12px;font-weight:600;line-height:20px;text-align:center}.steps>li>span{display:block;padding-top:1px}.steps strong{font-weight:650}.endpoint{display:flex;align-items:center;gap:12px;margin-top:12px;padding:12px 12px 12px 16px;border:1px solid #e5e5e5;border-radius:12px}.endpoint code{flex:1;min-width:0;overflow-wrap:anywhere;font-family:"SFMono-Regular",Consolas,"Liberation Mono",monospace;font-size:13px}.endpoint button{flex:none;padding:7px 14px;border:0;border-radius:8px;background:#000;color:#fff;font:inherit;font-size:13px;font-weight:600;cursor:pointer}ul{margin:20px 0 0;padding:0;list-style:none;border-top:1px solid #eee}ul li{padding:13px 0;border-bottom:1px solid #eee;color:#222}footer{padding:24px 32px;color:#888;font-size:12px}footer a{color:#888}@media(max-width:560px){header{padding:18px 16px}main{padding:8vh 16px 48px}h1{font-size:34px}footer{padding:20px 16px}}`;

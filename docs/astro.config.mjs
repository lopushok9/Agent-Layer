import { defineConfig } from "astro/config";
import starlight from "@astrojs/starlight";

export default defineConfig({
  integrations: [
    starlight({
      title: "AgentLayer Docs",
      description: "Documentation for the AgentLayer wallet and finance stack.",
      head: [],
      social: {
        github: "https://github.com/lopushok9/Agent-Layer"
      },
      sidebar: [
        {
          label: "Getting Started",
          items: [
            { label: "Overview", slug: "index" },
            { label: "Quick Start", slug: "getting-started/quick-start" }
          ]
        },
        {
          label: "Wallet",
          items: [
            { label: "Architecture", slug: "wallet/architecture" },
            { label: "Capabilities", slug: "wallet/capabilities" },
            { label: "Bitcoin Wallet", slug: "wallet/bitcoin" },
            { label: "Solana Wallet", slug: "wallet/solana" }
          ]
        },
        {
          label: "Infrastructure",
          items: [
            { label: "Provider Gateway", slug: "infrastructure/provider-gateway" },
            { label: "MCP Server", slug: "infrastructure/mcp-server" }
          ]
        }
      ]
    })
  ]
});

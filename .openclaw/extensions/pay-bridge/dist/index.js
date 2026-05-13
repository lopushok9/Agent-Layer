import {
  executePayApiRequest,
  getPayServiceEndpoints,
  getPayStatus,
  getPayWalletInfo,
  searchPayServices,
} from "./core.mjs";

const PLUGIN_ID = "pay-bridge";

function asContent(data) {
  return {
    content: [
      {
        type: "text",
        text: JSON.stringify(data, null, 2),
      },
    ],
  };
}

function resolvePluginConfig(api) {
  const globalConfig = api?.config ?? {};
  const pluginEntry = globalConfig?.plugins?.entries?.[PLUGIN_ID];
  return pluginEntry?.config ?? globalConfig?.config ?? {};
}

function registerTool(api, definition) {
  api.registerTool({
    name: definition.name,
    description: definition.description,
    parameters: definition.parameters,
    returns: {
      type: "object",
      additionalProperties: true,
    },
    async execute(_id, params = {}) {
      const config = resolvePluginConfig(api);
      let result;
      if (definition.name === "pay_status") {
        result = await getPayStatus(config, { cwd: process.cwd() });
      } else if (definition.name === "pay_wallet_info") {
        result = await getPayWalletInfo(config, { cwd: process.cwd() });
      } else if (definition.name === "pay_search_services") {
        result = await searchPayServices(config, params, { cwd: process.cwd() });
      } else if (definition.name === "pay_get_service_endpoints") {
        result = await getPayServiceEndpoints(config, params, { cwd: process.cwd() });
      } else if (definition.name === "pay_api_request") {
        result = await executePayApiRequest(config, params, { cwd: process.cwd() });
      } else {
        throw new Error(`Unsupported pay-bridge tool: ${definition.name}`);
      }
      return asContent(result);
    },
  });
}

const toolDefinitions = [
  {
    name: "pay_status",
    description:
      "Check whether the local pay.sh CLI is installed and whether a pay wallet/account is configured. Use this before any paid API workflow.",
    parameters: {
      type: "object",
      properties: {},
      additionalProperties: false,
    },
  },
  {
    name: "pay_wallet_info",
    description:
      "Show pay wallet/account status. This wallet is separate from the AgentLayer execution wallet and is only for pay.sh API payments.",
    parameters: {
      type: "object",
      properties: {},
      additionalProperties: false,
    },
  },
  {
    name: "pay_search_services",
    description:
      "Search the pay.sh skills catalog for paid APIs. Prefer this instead of guessing URLs manually.",
    parameters: {
      type: "object",
      properties: {
        query: {
          type: "string",
          description: "Search text for service names, descriptions, or endpoint paths.",
        },
        category: {
          type: "string",
          description: "Optional category filter such as ai_ml, maps, data, compute, search, crypto_finance.",
        },
        account: {
          type: "string",
          description: "Optional pay account override.",
        },
      },
      additionalProperties: false,
    },
  },
  {
    name: "pay_get_service_endpoints",
    description:
      "List the discoverable endpoints for a pay.sh service/resource pair and return their gateway URLs. Use the returned URL with pay_api_request.",
    parameters: {
      type: "object",
      properties: {
        service_fqn: {
          type: "string",
          description: "Fully qualified pay service name, for example solana-foundation/google/language.",
        },
        resource: {
          type: "string",
          description: "Resource name inside the service, for example entities or jobs.",
        },
        account: {
          type: "string",
          description: "Optional pay account override.",
        },
      },
      required: ["service_fqn", "resource"],
      additionalProperties: false,
    },
  },
  {
    name: "pay_api_request",
    description:
      "Call a paid API through the local pay.sh CLI using a URL returned by pay_get_service_endpoints. Requires explicit user_confirmed=true and keeps the pay wallet separate from AgentLayer execution wallets.",
    optional: true,
    parameters: {
      type: "object",
      properties: {
        service_fqn: {
          type: "string",
          description: "Fully qualified pay service name used to validate the request URL.",
        },
        resource: {
          type: "string",
          description: "Resource name used to validate the request URL.",
        },
        url: {
          type: "string",
          description: "Exact HTTPS gateway URL returned by pay_get_service_endpoints.",
        },
        method: {
          type: "string",
          description: "HTTP method such as GET or POST.",
        },
        headers: {
          type: "object",
          additionalProperties: { type: "string" },
          description: "Optional HTTP headers.",
        },
        query: {
          type: "object",
          additionalProperties: true,
          description: "Optional query parameters to append to the URL.",
        },
        json_body: {
          description: "Optional JSON request body.",
        },
        text_body: {
          type: "string",
          description: "Optional raw text request body. Do not provide with json_body.",
        },
        account: {
          type: "string",
          description: "Optional pay account override.",
        },
        parse_json_response: {
          type: "boolean",
          description: "If true, attempt to parse the response body as JSON.",
        },
        purpose: {
          type: "string",
          description: "Short user-facing reason for this paid API call.",
        },
        user_confirmed: {
          type: "boolean",
          description: "Must be true for paid API requests.",
        },
      },
      required: ["service_fqn", "resource", "url", "method", "purpose", "user_confirmed"],
      additionalProperties: false,
    },
  },
];

export default function registerPayBridgePlugin(api) {
  api?.logger?.info?.("[pay-bridge] registering pay.sh OpenClaw plugin");
  for (const definition of toolDefinitions) {
    registerTool(api, definition);
  }
  api?.logger?.info?.(`[pay-bridge] registered ${toolDefinitions.length} pay tools`);
}

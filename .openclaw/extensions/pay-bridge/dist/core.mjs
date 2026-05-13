import { execFile } from "node:child_process";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);
const ANSI_RE = /\u001b\[[0-9;]*m/g;

function stripAnsi(text) {
  return String(text || "").replace(ANSI_RE, "");
}

function nonEmptyLines(text) {
  return stripAnsi(text)
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

function extractLastJsonValue(text) {
  const lines = nonEmptyLines(text);
  for (let i = lines.length - 1; i >= 0; i -= 1) {
    const candidate = lines[i];
    if (!candidate.startsWith("{") && !candidate.startsWith("[")) continue;
    try {
      return JSON.parse(candidate);
    } catch {
      continue;
    }
  }
  return null;
}

function collectStringLeaves(value, acc = new Set()) {
  if (typeof value === "string") {
    acc.add(value);
    return acc;
  }
  if (Array.isArray(value)) {
    for (const item of value) collectStringLeaves(item, acc);
    return acc;
  }
  if (value && typeof value === "object") {
    for (const item of Object.values(value)) collectStringLeaves(item, acc);
  }
  return acc;
}

function withAccountArgs(args, account) {
  if (!account) return args;
  return [...args, "--account", account];
}

export function resolvePayBinary(config = {}) {
  return (
    config.payBinary ||
    process.env.OPENCLAW_PAY_BINARY ||
    "pay"
  );
}

export async function runPayCommand(payBinary, args, options = {}) {
  const { cwd, input = null } = options;
  let stdout = "";
  let stderr = "";
  try {
    const result = await execFileAsync(payBinary, args, {
      cwd,
      env: { ...process.env },
      input,
      maxBuffer: 1024 * 1024 * 8,
    });
    stdout = result.stdout ?? "";
    stderr = result.stderr ?? "";
  } catch (error) {
    stdout = typeof error?.stdout === "string" ? error.stdout : "";
    stderr = typeof error?.stderr === "string" ? error.stderr : "";
    const payload = extractLastJsonValue(stdout) || extractLastJsonValue(stderr);
    const message =
      payload?.error?.message ||
      payload?.message ||
      stripAnsi(stderr || stdout || error?.message || "pay command failed").trim() ||
      "pay command failed";
    const wrapped = new Error(message);
    wrapped.stdout = stdout;
    wrapped.stderr = stderr;
    wrapped.details = payload && typeof payload === "object" ? payload : null;
    throw wrapped;
  }
  return { stdout, stderr };
}

export function parseWhoamiOutput(stdout) {
  const lines = nonEmptyLines(stdout);
  const systemUser = lines[0] || null;
  const noAccount = lines.some((line) => /no mainnet account/i.test(line));
  return {
    system_user: systemUser,
    has_mainnet_account: !noAccount,
    raw_lines: lines,
  };
}

export function parseAccountListOutput(stdout) {
  const lines = nonEmptyLines(stdout);
  const noAccounts = lines.some((line) => /no accounts found/i.test(line));
  return {
    has_accounts: !noAccounts,
    raw_lines: lines,
  };
}

export async function getPayStatus(config = {}, options = {}) {
  const payBinary = resolvePayBinary(config);
  const versionResult = await runPayCommand(payBinary, ["--version"], options);
  const whoamiResult = await runPayCommand(
    payBinary,
    withAccountArgs(["whoami"], config.defaultAccount),
    options
  );
  const accountListResult = await runPayCommand(payBinary, ["account", "list"], options);
  return {
    installed: true,
    pay_binary: payBinary,
    version: stripAnsi(versionResult.stdout).trim() || null,
    account_configured: parseWhoamiOutput(whoamiResult.stdout).has_mainnet_account,
    has_any_accounts: parseAccountListOutput(accountListResult.stdout).has_accounts,
    whoami: parseWhoamiOutput(whoamiResult.stdout),
    accounts: parseAccountListOutput(accountListResult.stdout),
  };
}

export async function getPayWalletInfo(config = {}, options = {}) {
  const payBinary = resolvePayBinary(config);
  const whoamiResult = await runPayCommand(
    payBinary,
    withAccountArgs(["whoami"], config.defaultAccount),
    options
  );
  const accountListResult = await runPayCommand(payBinary, ["account", "list"], options);
  return {
    pay_binary: payBinary,
    default_account: config.defaultAccount || null,
    whoami: parseWhoamiOutput(whoamiResult.stdout),
    accounts: parseAccountListOutput(accountListResult.stdout),
    notes: [
      "This wallet is managed by pay.sh and is separate from the AgentLayer execution wallet.",
    ],
  };
}

export async function searchPayServices(config = {}, params = {}, options = {}) {
  const payBinary = resolvePayBinary(config);
  const args = ["skills", "search"];
  if (params.query) args.push(String(params.query));
  if (params.category) args.push("--category", String(params.category));
  args.push("--json");
  const { stdout, stderr } = await runPayCommand(
    payBinary,
    withAccountArgs(args, params.account || config.defaultAccount),
    options
  );
  const parsed = JSON.parse(stdout.trim() || "{}");
  return {
    query: params.query || "",
    category: params.category || null,
    results: parsed,
    warnings: nonEmptyLines(stderr),
  };
}

export async function getPayServiceEndpoints(config = {}, params = {}, options = {}) {
  const payBinary = resolvePayBinary(config);
  const args = [
    "skills",
    "endpoints",
    String(params.service_fqn),
    String(params.resource),
    "--json",
  ];
  const { stdout, stderr } = await runPayCommand(
    payBinary,
    withAccountArgs(args, params.account || config.defaultAccount),
    options
  );
  const parsed = JSON.parse(stdout.trim() || "{}");
  return {
    service_fqn: String(params.service_fqn),
    resource: String(params.resource),
    endpoints: parsed,
    warnings: nonEmptyLines(stderr),
  };
}

function ensureHttps(url, requireHttps = true) {
  if (!requireHttps) return;
  const parsed = new URL(url);
  if (parsed.protocol !== "https:") {
    throw new Error("pay_api_request only allows https URLs.");
  }
}

function appendQuery(url, query) {
  const parsed = new URL(url);
  if (query && typeof query === "object") {
    for (const [key, value] of Object.entries(query)) {
      if (value === undefined || value === null) continue;
      parsed.searchParams.set(key, String(value));
    }
  }
  return parsed.toString();
}

export function endpointPayloadContainsUrl(endpointPayload, url) {
  const strings = collectStringLeaves(endpointPayload);
  return strings.has(url);
}

export async function executePayApiRequest(config = {}, params = {}, options = {}) {
  if (params.user_confirmed !== true) {
    throw new Error("pay_api_request requires user_confirmed=true.");
  }
  if (!params.purpose || !String(params.purpose).trim()) {
    throw new Error("pay_api_request requires a non-empty purpose.");
  }
  if (!params.service_fqn || !params.resource || !params.url) {
    throw new Error("pay_api_request requires service_fqn, resource, and url.");
  }
  if (params.json_body !== undefined && params.text_body !== undefined) {
    throw new Error("Provide either json_body or text_body, not both.");
  }

  const endpointData = await getPayServiceEndpoints(config, {
    account: params.account,
    resource: params.resource,
    service_fqn: params.service_fqn,
  }, options);

  const finalUrl = appendQuery(String(params.url), params.query);
  ensureHttps(finalUrl, config.requireHttps !== false);
  if (!endpointPayloadContainsUrl(endpointData.endpoints, String(params.url))) {
    throw new Error("The requested URL is not present in pay_get_service_endpoints for this service/resource.");
  }

  const payBinary = resolvePayBinary(config);
  const method = String(params.method || "GET").toUpperCase();
  const args = ["curl"];
  if (params.account || config.defaultAccount) {
    args.push("--account", String(params.account || config.defaultAccount));
  }
  args.push("--request", method);

  const headers = params.headers && typeof params.headers === "object" ? params.headers : {};
  for (const [key, value] of Object.entries(headers)) {
    args.push("--header", `${key}: ${String(value)}`);
  }

  if (params.json_body !== undefined) {
    const hasContentType = Object.keys(headers).some((key) => key.toLowerCase() === "content-type");
    if (!hasContentType) {
      args.push("--header", "content-type: application/json");
    }
    args.push("--data", JSON.stringify(params.json_body));
  } else if (params.text_body !== undefined) {
    args.push("--data", String(params.text_body));
  }

  args.push(finalUrl);
  const { stdout, stderr } = await runPayCommand(payBinary, args, options);
  const trimmed = stdout.trim();
  let responseBody = trimmed;
  if (params.parse_json_response !== false) {
    try {
      responseBody = JSON.parse(trimmed);
    } catch {
      responseBody = trimmed;
    }
  }
  return {
    method,
    purpose: String(params.purpose),
    request_url: finalUrl,
    service_fqn: String(params.service_fqn),
    resource: String(params.resource),
    response: responseBody,
    raw_response_text: trimmed,
    warnings: nonEmptyLines(stderr),
  };
}

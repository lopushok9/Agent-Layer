import assert from "node:assert/strict";

import {
  endpointPayloadContainsUrl,
  parseAccountListOutput,
  parseWhoamiOutput,
} from "./core.mjs";

const whoami = parseWhoamiOutput(`
yuriytsygankov
\u001b[2m(no mainnet account — run \`pay setup\`)\u001b[0m
`);
assert.equal(whoami.system_user, "yuriytsygankov");
assert.equal(whoami.has_mainnet_account, false);

const accounts = parseAccountListOutput(`
\u001b[2mNo accounts found. Run \`pay account new\` to create one.\u001b[0m
`);
assert.equal(accounts.has_accounts, false);

const endpointPayload = {
  endpoints: [
    {
      method: "POST",
      url: "https://api.example.com/v1/invoke",
    },
  ],
};
assert.equal(
  endpointPayloadContainsUrl(endpointPayload, "https://api.example.com/v1/invoke"),
  true
);
assert.equal(
  endpointPayloadContainsUrl(endpointPayload, "https://api.example.com/v1/other"),
  false
);

console.log("smoke_pay_bridge: ok");

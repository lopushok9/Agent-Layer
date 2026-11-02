import test from "node:test";
import assert from "node:assert/strict";
import { encodeAbiParameters, encodeFunctionData, parseAbi, parseAbiParameters } from "viem";
import { inspectCall } from "../src/nested-calls.js";
const pos = "0x7C5f5A4bBd8fD63184577525326123B519429bDc";
test("inspect Uniswap v4 nested burn minimums without changing calldata", () => {
  const burn = encodeAbiParameters(parseAbiParameters("uint256,uint128,uint128,bytes"), [123n, 45n, 67n, "0x"]);
  const data = encodeAbiParameters(parseAbiParameters("bytes,bytes[]"), ["0x03", [burn]]);
  const call = encodeFunctionData({abi:parseAbi(["function modifyLiquidities(bytes,uint256) payable"]),functionName:"modifyLiquidities",args:[data,123456n]});
  const result: any = inspectCall(pos, call);
  assert.equal(result.actions[0].name, "burn_position");
  assert.deepEqual(result.actions[0].parameters, ["123","45","67","0x"]);
  assert.equal(inspectCall("0x1111111111111111111111111111111111111111",call), null);
});
test("inspect CREATE2 factory salt and init code, never as proof of deployment", () => {
  const result: any = inspectCall("0x4e59b44847b379578588920cA78FbF26c0B4956C", `0x${"00".repeat(32)}6000`);
  assert.equal(result.kind,"create2_factory"); assert.match(result.predicted_address,/^0x[0-9a-fA-F]{40}$/);
  assert.match(result.warning,/verify factory/);
});

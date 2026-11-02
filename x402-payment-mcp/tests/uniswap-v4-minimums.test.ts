import test from "node:test";
import assert from "node:assert/strict";
import { decodeAbiParameters, decodeFunctionData, encodeAbiParameters, encodeFunctionData, parseAbi, parseAbiParameters, zeroAddress } from "viem";
import { protectV4Burn, v4BurnCandidate } from "../src/uniswap-v4-minimums.js";
const account="0x1111111111111111111111111111111111111111" as const, pos="0x7C5f5A4bBd8fD63184577525326123B519429bDc" as const, token="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913" as const, native="0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee" as const;
const abi=parseAbi(["function modifyLiquidities(bytes unlockData,uint256 deadline) payable"]), cmds=parseAbiParameters("bytes,bytes[]"), burn=parseAbiParameters("uint256,uint128,uint128,bytes"), take=parseAbiParameters("address,address,address");
function call(min0=0n,min1=0n,recipient:`0x${string}`=account){const parts=[encodeAbiParameters(burn,[4n,min0,min1,"0x"]),encodeAbiParameters(take,[zeroAddress,token,recipient])];return {to:pos,value:"0",data:encodeFunctionData({abi,functionName:"modifyLiquidities",args:[encodeAbiParameters(cmds,["0x0311",parts]),9999999999n]})};}
const changes=(a:string,b:string)=>[{token:{address:native},value:{diff:a}},{token:{address:token},value:{diff:b}}];
const simulation={block_number:"123",asset_changes:changes("1000","2000")};
const rpc=(hooks:`0x${string}`=zeroAddress)=>({readContract:async (p:any)=>{assert.equal(p.blockNumber,123n);return [{currency0:zeroAddress,currency1:token,hooks},"0x"]}} as any);
function minimums(data:`0x${string}`){const d=decodeFunctionData({abi,data});const [,p]=decodeAbiParameters(cmds,d.args[0]);return decodeAbiParameters(burn,p[0]!);}

test("protects principal excluding fees, preserves stronger minimum, and keeps calldata fixed otherwise",async()=>{
 const candidate=v4BurnCandidate("base",account,[call(989n)])!;let seen=false;
 const result=await protectV4Burn("base",account,candidate,simulation,50,rpc(),async(_n,_a,c,block)=>{seen=true;assert.equal(block,123n);assert.notEqual(c[0]!.data,candidate.call.data);return {block_number:"123",asset_changes:changes("10","100")}});
 assert.ok(seen);assert.deepEqual(minimums(result.call.data),[4n,989n,1890n,"0x"]);assert.deepEqual(result.details.principal,["990","1900"]);
});

test("fails closed when fee calculation or hook behavior is unsafe",async()=>{
 const candidate=v4BurnCandidate("base",account,[call()])!;
 await assert.rejects(protectV4Burn("base",account,candidate,simulation,50,rpc("0x0000000000000000000000000000000000000200"),async()=>simulation),/liquidity-removal hooks/);
 await assert.rejects(protectV4Burn("base",account,candidate,simulation,50,rpc(),async()=>({block_number:"124",asset_changes:[]})),/block mismatch/);
 await assert.rejects(protectV4Burn("base",account,candidate,simulation,50,rpc(),async()=>({block_number:"123",asset_changes:changes("1001","0")})),/separate/);
 assert.equal(v4BurnCandidate("base",account,[call(),call()]),null);
 assert.equal(v4BurnCandidate("base",account,[call(0n,0n,"0x2222222222222222222222222222222222222222")]),null);
});

test("dust rounds to zero without blocking the other protected asset",async()=>{
 const candidate=v4BurnCandidate("base",account,[call()])!;
 const r=await protectV4Burn("base",account,candidate,{block_number:"123",asset_changes:changes("1","2000")},50,rpc(),async()=>({block_number:"123",asset_changes:[]}));
 assert.deepEqual(minimums(r.call.data),[4n,0n,1990n,"0x"]);
 assert.match(r.details.note,/zero offers no protection/);
});

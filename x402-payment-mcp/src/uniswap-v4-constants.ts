import { parseAbi, parseAbiParameters } from "viem";
import type { WalletNetwork } from "./transaction-builder.js";

export const v4PositionManagers: Record<WalletNetwork, string> = { base: "0x7c5f5a4bbd8fd63184577525326123b519429bdc", ethereum: "0xbd216513d74c8cf14cf4747e6aaa6420ff64ee9e" };
export const v4ModifyAbi = parseAbi(["function modifyLiquidities(bytes unlockData,uint256 deadline) payable"]);
export const v4Commands = parseAbiParameters("bytes,bytes[]");
export const v4BurnParams = parseAbiParameters("uint256 tokenId,uint128 amount0Min,uint128 amount1Min,bytes hookData");
export const v4TakeParams = parseAbiParameters("address currency0,address currency1,address recipient");

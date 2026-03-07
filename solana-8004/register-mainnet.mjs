import 'dotenv/config';

import { Keypair } from '@solana/web3.js';
import {
  IPFSClient,
  SolanaSDK,
  ServiceType,
  buildRegistrationFileJson,
} from '8004-solana';

function required(name) {
  const value = process.env[name]?.trim();
  if (!value) {
    throw new Error(`Missing required env var: ${name}`);
  }
  return value;
}

function parseSecretKey(name) {
  const raw = required(name);
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new Error(`${name} must be a JSON array, for example: [1,2,3,...]`);
  }

  if (!Array.isArray(parsed) || !parsed.every((n) => Number.isInteger(n))) {
    throw new Error(`${name} must be a JSON array of integers`);
  }

  return Uint8Array.from(parsed);
}

function optional(name) {
  const value = process.env[name]?.trim();
  return value ? value : undefined;
}

function splitCsv(name) {
  const raw = optional(name);
  if (!raw) return undefined;
  const items = raw.split(',').map((v) => v.trim()).filter(Boolean);
  return items.length > 0 ? items : undefined;
}

function buildServices() {
  const services = [];
  const mcp = optional('AGENT_MCP_URL');
  const a2a = optional('AGENT_A2A_URL');
  const oasf = optional('AGENT_OASF_URL');

  if (mcp) services.push({ type: ServiceType.MCP, value: mcp });
  if (a2a) services.push({ type: ServiceType.A2A, value: a2a });
  if (oasf) services.push({ type: ServiceType.OASF, value: oasf });

  if (services.length === 0) {
    throw new Error('At least one service URL is required. Set AGENT_MCP_URL or AGENT_A2A_URL or AGENT_OASF_URL.');
  }

  return services;
}

function assertEnvForCheckOnly() {
  required('SOLANA_PRIVATE_KEY');
  required('PINATA_JWT');
  required('AGENT_NAME');
  required('AGENT_DESCRIPTION');
  required('AGENT_IMAGE_URI');
  buildServices();
  required('COLLECTION_NAME');
  required('COLLECTION_SYMBOL');
  required('COLLECTION_DESCRIPTION');
}

async function main() {
  const checkOnly = process.argv.includes('--check-only');
  assertEnvForCheckOnly();

  if (checkOnly) {
    console.log('Environment looks valid for mainnet registration.');
    return;
  }

  const signer = Keypair.fromSecretKey(parseSecretKey('SOLANA_PRIVATE_KEY'));
  const ipfs = new IPFSClient({
    pinataEnabled: true,
    pinataJwt: required('PINATA_JWT'),
  });

  const rpcUrl = optional('SOLANA_RPC_URL');
  const agentRegistryProgramId = optional('SOLANA_AGENT_REGISTRY_PROGRAM_ID');
  const atomEngineProgramId = optional('SOLANA_ATOM_ENGINE_PROGRAM_ID');
  const sdk = new SolanaSDK({
    cluster: 'mainnet-beta',
    signer,
    ipfsClient: ipfs,
    ...(rpcUrl ? { rpcUrl } : {}),
    ...((agentRegistryProgramId || atomEngineProgramId)
      ? {
          programIds: {
            ...(agentRegistryProgramId ? { agentRegistry: agentRegistryProgramId } : {}),
            ...(atomEngineProgramId ? { atomEngine: atomEngineProgramId } : {}),
          },
        }
      : {}),
  });

  const collectionInput = {
    name: required('COLLECTION_NAME'),
    symbol: required('COLLECTION_SYMBOL'),
    description: required('COLLECTION_DESCRIPTION'),
    image: optional('COLLECTION_IMAGE_URI'),
    banner_image: optional('COLLECTION_BANNER_URI'),
    socials: {
      website: optional('COLLECTION_WEBSITE'),
      x: optional('COLLECTION_X'),
      discord: optional('COLLECTION_DISCORD'),
    },
  };

  const collection = await sdk.createCollection(collectionInput);
  if (!collection.pointer) {
    throw new Error('Collection pointer was not returned from createCollection()');
  }

  const metadata = buildRegistrationFileJson({
    name: required('AGENT_NAME'),
    description: required('AGENT_DESCRIPTION'),
    image: required('AGENT_IMAGE_URI'),
    services: buildServices(),
    skills: splitCsv('AGENT_SKILLS'),
    domains: splitCsv('AGENT_DOMAINS'),
  });

  const metadataCid = await ipfs.addJson(metadata);
  const metadataUri = `ipfs://${metadataCid}`;

  const registered = await sdk.registerAgent(metadataUri);
  if (!registered?.success) {
    throw new Error(`registerAgent failed: ${registered?.error ?? 'unknown error'}`);
  }
  if (!registered.asset) {
    throw new Error('registerAgent returned no asset pubkey');
  }

  if (collection.pointer) {
    const pointerSet = await sdk.setCollectionPointer(registered.asset, collection.pointer);
    if (typeof pointerSet === 'object' && 'success' in pointerSet && !pointerSet.success) {
      throw new Error(`setCollectionPointer failed: ${pointerSet.error ?? 'unknown error'}`);
    }
  }

  const opWalletRaw = optional('OP_WALLET_PRIVATE_KEY');
  const opWallet = opWalletRaw
    ? Keypair.fromSecretKey(Uint8Array.from(JSON.parse(opWalletRaw)))
    : Keypair.generate();

  await sdk.setAgentWallet(registered.asset, opWallet);

  console.log('Registration completed on mainnet-beta');
  console.log(`Collection URI: ${collection.uri ?? 'n/a'}`);
  console.log(`Collection pointer: ${collection.pointer}`);
  console.log(`Agent asset: ${registered.asset.toBase58()}`);
  console.log(`Register tx: ${registered.signature}`);
  console.log(`Operational wallet pubkey: ${opWallet.publicKey.toBase58()}`);

  if (!opWalletRaw) {
    console.log('Operational wallet secret key (store securely):');
    console.log(JSON.stringify(Array.from(opWallet.secretKey)));
  }
}

main().catch((error) => {
  if (error instanceof Error) {
    console.error('Registration failed:', error.message);
    if (error.stack) {
      console.error(error.stack);
    }
  } else {
    console.error('Registration failed:', error);
  }
  process.exit(1);
});

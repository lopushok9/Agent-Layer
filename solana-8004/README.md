# 8004 Solana Mainnet Registration

This folder contains a minimal, safe flow to register an 8004 agent on Solana `mainnet-beta` using `PINATA_JWT`.

## Step 1: Get `PINATA_JWT`

In Pinata dashboard:
1. Open `API Keys`.
2. Create a new key with upload permissions.
3. Copy the JWT token value.

Reference from 8004 quickstart:
- https://8004.qnt.sh/#quickstart
- https://github.com/QuantuLabs/8004-solana-ts/blob/main/docs/QUICKSTART.md

## Step 2: Prepare env

```bash
cd solana-8004
cp .env.example .env
```

Fill required values in `.env`:
- `SOLANA_PRIVATE_KEY` in JSON array format
- `PINATA_JWT`
- agent metadata fields
- at least one service endpoint (`AGENT_MCP_URL` or `AGENT_A2A_URL` or `AGENT_OASF_URL`)

## Step 3: Install deps

```bash
npm install
```

## Step 4: Validate env only (no tx)

```bash
npm run check:env
```

## Upload images/files to IPFS (Pinata)

If you have local files, upload them first and use returned `ipfs://...` values in `.env`.

```bash
# agent avatar
npm run upload:ipfs -- ./assets/agent.png

# collection image
npm run upload:ipfs -- ./assets/collection.png
```

Then set:
- `AGENT_IMAGE_URI=ipfs://...`
- `COLLECTION_IMAGE_URI=ipfs://...`
- `COLLECTION_BANNER_URI=ipfs://...` (optional)

## Step 5: Register on mainnet

```bash
npm run register:mainnet
```

Output includes:
- collection pointer (`c1:...`)
- registered agent asset pubkey
- registration tx signature
- operational wallet pubkey

If `OP_WALLET_PRIVATE_KEY` is empty, script generates one and prints it once.

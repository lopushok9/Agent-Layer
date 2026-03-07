import 'dotenv/config';

import fs from 'node:fs';
import path from 'node:path';

function required(name) {
  const value = process.env[name]?.trim();
  if (!value) {
    throw new Error(`Missing required env var: ${name}`);
  }
  return value;
}

function usage() {
  throw new Error('Usage: npm run upload:ipfs -- <relative-or-absolute-file-path>');
}

function detectMimeType(filename) {
  const ext = path.extname(filename).toLowerCase();
  if (ext === '.png') return 'image/png';
  if (ext === '.jpg' || ext === '.jpeg') return 'image/jpeg';
  if (ext === '.webp') return 'image/webp';
  if (ext === '.gif') return 'image/gif';
  if (ext === '.svg') return 'image/svg+xml';
  if (ext === '.json') return 'application/json';
  return 'application/octet-stream';
}

async function main() {
  const filepath = process.argv[2];
  if (!filepath) usage();

  const absolutePath = path.resolve(filepath);
  if (!fs.existsSync(absolutePath)) {
    throw new Error(`File not found: ${absolutePath}`);
  }

  const pinataJwt = required('PINATA_JWT');
  const fileBytes = fs.readFileSync(absolutePath);
  const filename = path.basename(absolutePath);
  const mimeType = detectMimeType(filename);

  const formData = new FormData();
  formData.append('file', new Blob([fileBytes], { type: mimeType }), filename);
  formData.append('network', 'public');

  const response = await fetch('https://uploads.pinata.cloud/v3/files', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${pinataJwt}`,
    },
    body: formData,
    redirect: 'error',
  });

  if (!response.ok) {
    const errorText = await response.text().catch(() => '');
    throw new Error(`Pinata upload failed: HTTP ${response.status} ${errorText}`);
  }

  const payload = await response.json();
  const cid = payload?.data?.cid;
  if (!cid) {
    throw new Error(`Pinata response did not include CID: ${JSON.stringify(payload)}`);
  }

  console.log(`Uploaded: ${absolutePath}`);
  console.log(`CID: ${cid}`);
  console.log(`URI: ipfs://${cid}`);
}

main().catch((error) => {
  console.error('Upload failed:', error instanceof Error ? error.message : error);
  process.exit(1);
});

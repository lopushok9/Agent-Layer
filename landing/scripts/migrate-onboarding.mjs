import { readFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import pg from 'pg'

const { Client } = pg
const scriptDirectory = path.dirname(fileURLToPath(import.meta.url))
const migrationPath = path.resolve(scriptDirectory, '../migrations/001_welcome_onboarding.sql')
const databaseUrl = String(process.env.DATABASE_URL || '').trim()

if (!databaseUrl) {
  throw new Error('DATABASE_URL is required to run onboarding migrations.')
}

const client = new Client({
  connectionString: databaseUrl,
  ssl: process.env.NODE_ENV === 'production' ? { rejectUnauthorized: true } : undefined,
})

try {
  const sql = await readFile(migrationPath, 'utf8')
  await client.connect()
  await client.query(sql)
  console.log(`Applied ${path.basename(migrationPath)}`)
} finally {
  await client.end()
}

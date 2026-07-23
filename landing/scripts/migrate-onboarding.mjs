import { readdir, readFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import pg from 'pg'

const { Client } = pg
const scriptDirectory = path.dirname(fileURLToPath(import.meta.url))
const migrationsDirectory = path.resolve(scriptDirectory, '../migrations')
const databaseUrl = String(process.env.DATABASE_URL || '').trim()

if (!databaseUrl) {
  throw new Error('DATABASE_URL is required to run onboarding migrations.')
}

const client = new Client({
  connectionString: databaseUrl,
  ssl: process.env.NODE_ENV === 'production' ? { rejectUnauthorized: true } : undefined,
})

try {
  await client.connect()
  const migrationNames = (await readdir(migrationsDirectory))
    .filter((name) => name.endsWith('.sql'))
    .sort()
  for (const migrationName of migrationNames) {
    const migrationPath = path.join(migrationsDirectory, migrationName)
    const sql = await readFile(migrationPath, 'utf8')
    await client.query(sql)
    console.log(`Applied ${migrationName}`)
  }
} finally {
  await client.end()
}

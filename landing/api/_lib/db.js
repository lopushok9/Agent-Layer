import { attachDatabasePool } from '@vercel/functions'
import pg from 'pg'

import { requireDatabaseUrl } from './config.js'

const { Pool } = pg

let pool
let attached = false

export function getPool(env = process.env) {
  if (!pool) {
    pool = new Pool({
      connectionString: requireDatabaseUrl(env),
      idleTimeoutMillis: 5_000,
      connectionTimeoutMillis: 5_000,
      max: 10,
      ssl: env.NODE_ENV === 'production' ? { rejectUnauthorized: true } : undefined,
    })
  }

  if (!attached) {
    attachDatabasePool(pool)
    attached = true
  }

  return pool
}

export async function withTransaction(callback, database = getPool()) {
  const client = await database.connect()
  try {
    await client.query('BEGIN')
    const result = await callback(client)
    await client.query('COMMIT')
    return result
  } catch (error) {
    await client.query('ROLLBACK')
    throw error
  } finally {
    client.release()
  }
}

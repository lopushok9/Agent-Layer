import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { describe, it } from 'node:test'

import { getSchema } from 'better-auth/db'

import { configuredAuthProviders } from '../../api/_lib/auth.js'

const migrationUrl = new URL('../../migrations/000_better_auth.sql', import.meta.url)

describe('Better Auth configuration', () => {
  it('enables GitHub and X independently from server credentials', () => {
    assert.deepEqual(configuredAuthProviders({}), [])
    assert.deepEqual(
      configuredAuthProviders({
        GITHUB_CLIENT_ID: 'id',
        GITHUB_CLIENT_SECRET: 'secret',
      }),
      ['github'],
    )
    assert.deepEqual(
      configuredAuthProviders({
        X_CLIENT_ID: 'id',
        X_CLIENT_SECRET: 'secret',
      }),
      ['x'],
    )
  })

  it('keeps the checked-in migration aligned with Better Auth core fields', async () => {
    const sql = await readFile(migrationUrl, 'utf8')
    const schema = getSchema({})

    for (const [modelName, model] of Object.entries(schema)) {
      assert.match(sql, new RegExp(`CREATE TABLE IF NOT EXISTS "?${modelName}"?`))
      for (const field of Object.values(model.fields)) {
        const escapedName = field.fieldName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
        assert.match(sql, new RegExp(`"?${escapedName}"?`))
      }
    }
  })
})

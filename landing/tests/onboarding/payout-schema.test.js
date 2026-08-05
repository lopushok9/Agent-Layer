import assert from 'node:assert/strict'
import { readdir, readFile } from 'node:fs/promises'
import { describe, it } from 'node:test'

const migrationsUrl = new URL('../../migrations/', import.meta.url)
const payoutMigrationUrl = new URL('002_payout_tracking.sql', migrationsUrl)

describe('payout tracking migration', () => {
  it('records who was paid, with what, and when', async () => {
    const sql = await readFile(payoutMigrationUrl, 'utf8')

    for (const column of ['payout_status', 'payout_tx_hash', 'paid_at']) {
      assert.match(sql, new RegExp(`ADD COLUMN IF NOT EXISTS ${column}\\b`))
    }

    // A row must not be able to claim payment without the transaction proving it.
    assert.match(sql, /payout_status = 'sent' AND payout_tx_hash IS NOT NULL AND paid_at IS NOT NULL/)

    // Reusing a transaction hash must not register as a second payout.
    assert.match(sql, /CREATE UNIQUE INDEX IF NOT EXISTS onboarding_invites_payout_tx_unique/)
  })

  it('re-runs safely, because the migrate script replays every file each time', async () => {
    const names = (await readdir(migrationsUrl)).filter((name) => name.endsWith('.sql')).sort()
    assert.ok(names.includes('002_payout_tracking.sql'))

    for (const name of names) {
      const sql = await readFile(new URL(name, migrationsUrl), 'utf8')
      const withoutComments = sql.replace(/^\s*--.*$/gm, '')

      // DO blocks carry their own IF NOT EXISTS conditions, checked separately
      // below; lifting them out keeps statement splitting from cutting them up.
      const topLevel = withoutComments.replace(/DO \$\$[\s\S]*?\$\$;/g, '')

      const unguarded = topLevel
        .split(';')
        .map((statement) => statement.trim().replace(/\s+/g, ' '))
        .filter((statement) => /^(CREATE (TABLE|UNIQUE )?(INDEX)?|ALTER TABLE)/i.test(statement))
        .filter((statement) => !/IF NOT EXISTS/i.test(statement))

      assert.deepEqual(unguarded, [], `${name} has statements that cannot re-run`)

      // ADD CONSTRAINT has no IF NOT EXISTS in Postgres, so each one must sit
      // behind an explicit pg_constraint lookup.
      const addConstraints = (withoutComments.match(/ADD CONSTRAINT/gi) || []).length
      const guards = (withoutComments.match(/FROM pg_constraint WHERE conname/gi) || []).length
      assert.equal(addConstraints, guards, `${name} adds constraints without an existence guard`)
    }
  })
})

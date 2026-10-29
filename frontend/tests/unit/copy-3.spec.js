/**
 * Copy pass 3's words (prp/2026-10-29-ux-pass/COPY.md): times from the as of in words, accounts
 * by name, and the context bar's tag for figures that are not the observed snapshot.
 */
import { describe, expect, it } from 'vitest'
import { AGENTS, PLAIN, accountName, asOfText, contextTag, hoursFrom, projectionTerms } from '../../src/api/v1.js'

const AS_OF = '2026-01-01T00:00:00Z'

describe('copy pass 3', () => {
  it('says a time from the as of in words, never t=', () => {
    expect(hoursFrom(AS_OF, '2026-01-02T16:00:00Z')).toBe('in 40 hours')
    expect(hoursFrom(AS_OF, '2026-01-03T00:00:00Z')).toBe('in 2 days')
    expect(hoursFrom(AS_OF, AS_OF)).toBe('now')
    expect(hoursFrom(AS_OF, '2025-12-31T21:00:00Z')).toBe('3 hours ago')
    expect(hoursFrom(AS_OF, 'not a time')).toBe('at an unknown time')
    expect(asOfText(AS_OF)).toBe('1 Jan, 00:00 UTC')
  })

  it('names an account by its kind, its owner first when asked, a currency kind once', () => {
    expect(accountName('treasury/operating', { currency: 'USD' })).toBe('Operating account · USD')
    expect(accountName('lender/stale-venue', { owner: true })).toBe('Lender stale venue account')
    expect(accountName('treasury/eur', { currency: 'EUR' })).toBe('EUR account')
    expect(accountName('lender-pool', { owner: true })).toBe('Lender pool account')
  })

  it('tags a replayed what-if as both, so recorded figures never read as live ones', () => {
    expect(contextTag({ replay: true, branch_id: 'b1' })).toBe(`${PLAIN.replay} · ${PLAIN.branch}`)
    expect(contextTag({ branch_id: 'b1' })).toBe(PLAIN.branch)
    expect(contextTag({ replay: true })).toBe(PLAIN.replay)
    expect(contextTag({ snapshot_id: 'demo-world' })).toBe('')
  })

  it('says what P leaves out as due after the point, never as counted later', () => {
    const account = {
      id: 'treasury/operating', currency: 'USD',
      buckets: { settled: { minor: 100, currency: 'USD' }, pending_in: [], pending_out: [] },
      projected: [{ t: '2026-01-02T16:00:00Z', value: { minor: 100, currency: 'USD', status: 'known' } }]
    }
    const rent = { obligation_id: 'r2', account: 'treasury/operating', kind: 'rent', due_at: '2026-01-03T04:00:00Z', amount: { minor: 50, currency: 'USD' } }
    expect(projectionTerms(account, '2026-01-02T16:00:00Z', [rent], AS_OF).excluded)
      .toBe('due after this point (in 40 hours), so not counted: rent r2 due (in 52 hours)')
  })

  it('keeps the agents apart from the modes', () => {
    expect(AGENTS.scripted).toBe('Scripted agents')
    expect(AGENTS.replay).toBeUndefined()
  })
})

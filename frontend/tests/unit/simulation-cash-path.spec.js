import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import CashPaths from '../../src/components/CashPaths.vue'

const epoch = Date.parse('2026-01-01T00:00:00Z')
const point = (h, minor, status = 'known') => ({ t: new Date(epoch + h * 3600000).toISOString(), value: { minor, currency: 'USD', status } })
const props = () => ({ round: 5, at: epoch + 20 * 3600000, epoch,
  account: { id: 'treasury/operating', currency: 'USD', floor: { minor: 3000000, currency: 'USD', status: 'known' } },
  branches: [{ branch_id: 'base', parent_branch_id: null, policy: null }, { branch_id: 'none', parent_branch_id: 'base', policy: 'no-action' }],
  paths: [{ branch_id: 'base', account_id: 'treasury/operating', points: [point(0, 7000000), point(4, 7000000)] },
    { branch_id: 'none', account_id: 'treasury/operating', points: [point(8, 7000000), point(40, 2000000), point(72, 3500000)] }]
})

describe('Simulation cash outlook', () => {
  it('never labels another entity’s recorded account as treasury when metadata is absent', () => {
    const p = props()
    p.account = null
    for (const path of p.paths) path.account_id = 'lender-pool'
    const w = mount(CashPaths, { props: p })
    expect(w.find('[data-test="policy-chart"]').exists()).toBe(false)
    expect(w.text()).toContain('Treasury account not identified')
    w.unmount()
  })
  it('reads the available policy currency when the base path has no points', () => {
    const p = props()
    p.account = null
    p.paths[0].points = []
    for (const point of p.paths[1].points) point.value.currency = 'EUR'
    const w = mount(CashPaths, { props: p })
    expect(w.get('[data-policy="no-action"]').attributes('d')).toMatch(/^M/)
    expect(w.get('.lw-cash-chart__axes').text()).toContain('€')
    w.unmount()
  })
  it('does not invent an observation timestamp from a point’s scenario time', () => {
    const w = mount(CashPaths, { props: props() })
    const tips = w.findAll('.lw-cash-chart__point [role="tooltip"]').map((x) => x.text()).join(' ')
    expect(tips).toContain('Observation time unavailable')
    expect(tips).not.toContain('as of 2026-')
    w.unmount()
  })
  it('still draws run-owned paths when the auxiliary treasury reading is unavailable', () => {
    const w = mount(CashPaths, { props: { ...props(), account: null } })
    expect(w.find('[data-test="policy-chart"]').exists()).toBe(true)
    expect(w.find('[data-test="cash-floor"]').exists()).toBe(false)
    expect(w.get('[data-test="floor-unavailable"]').text()).toContain('Reserve floor unavailable')
    w.unmount()
  })
  it('labels replayed policy curves visibly even when the base is fresh', () => {
    const p = props()
    p.branches[1].replay = true
    const w = mount(CashPaths, { props: p })
    expect(w.get('.lw-cash-chart__legend').text()).toContain('Do nothing · Replay')
    w.unmount()
  })
  it('uses a full-height hour target rather than a target only at the top curve', () => {
    const w = mount(CashPaths, { props: props() })
    expect(w.get('.lw-cash-chart__point').attributes('style')).toContain('top: 12px')
    w.unmount()
  })
  it('plots API paths from the parent prefix and names the real low-point gap', () => {
    const w = mount(CashPaths, { props: props() })
    expect(w.get('[data-policy="no-action"]').attributes('d')).toMatch(/^M64,/)
    expect(w.get('[data-test="cash-shortfall"]').text()).toContain('$10,000 at h40')
    expect(w.findAll('[data-test="cash-point"]')).toHaveLength(5)
    w.unmount()
  })
  it('unknown points break the path and suppress an unprovable minimum', () => {
    const p = props()
    p.paths[1].points[1] = point(40, null, 'unknown')
    const w = mount(CashPaths, { props: p })
    expect(w.find('[data-test="cash-shortfall"]').exists()).toBe(false)
    expect(w.get('[data-policy="no-action"]').attributes('d').match(/M/g)).toHaveLength(2)
    expect(w.findAll('[data-test="cash-point"]').some((x) => x.attributes('aria-label').includes('Unknown'))).toBe(true)
    w.unmount()
  })
  it('never compares a foreign-currency floor or an unrelated account', () => {
    const p = props()
    p.account.floor.currency = 'EUR'
    const w = mount(CashPaths, { props: p })
    expect(w.find('[data-test="cash-floor"]').exists()).toBe(false)
    expect(w.find('[data-test="cash-shortfall"]').exists()).toBe(false)
    w.unmount()
    p.account.id = 'other/operating'
    const missing = mount(CashPaths, { props: p })
    expect(missing.find('[data-test="policy-chart"]').exists()).toBe(false)
    missing.unmount()
  })
  it('an unloaded round shows no substitute value or outlook', () => {
    const w = mount(CashPaths, { props: { ...props(), at: null } })
    expect(w.get('[data-test="cash-unloaded"]').text()).toBe('Round not loaded')
    expect(w.find('[data-test="policy-chart"]').exists()).toBe(false)
    expect(w.find('[data-test="cash-value"]').exists()).toBe(false)
    w.unmount()
  })
})

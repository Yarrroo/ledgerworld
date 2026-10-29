/**
 * The demonstration world's topology (scenarios/world.json): its eight actors, what each one is
 * for, and the structural relationships between them — contracts, obligations, shared venue
 * exposures and the price feed. It is read only for the snapshot it names: a response about any
 * other snapshot gets `null`, and the screen says it has no map. It carries no amount the
 * screens show; money comes from the API alone.
 */
import world from '../../../scenarios/world.json'
import delayedReceipt from '../../../scenarios/families/delayed-receipt.json'
import fxGap from '../../../scenarios/families/fx-gap.json'
import stablecoinDepeg from '../../../scenarios/families/stablecoin-depeg.json'
import redemptionSpike from '../../../scenarios/families/redemption-spike.json'
import borrowerSilence from '../../../scenarios/families/borrower-silence.json'
import confidenceRumour from '../../../scenarios/families/confidence-rumour.json'

/** The six scenario families, in the handoff's order: id, what happens, and its parameters. */
export const FAMILIES = [delayedReceipt, fxGap, stablecoinDepeg, redemptionSpike, borrowerSilence, confidenceRumour]
  .map((f) => ({ id: f.id, about: f.about, params: f.params ?? {}, startsRound: f.starts_round ?? null }))

/** The family a cohort or branch label names ("delayed-receipt seed 7: …"), or null. */
export function familyOf (text) {
  return FAMILIES.find((f) => String(text ?? '').includes(f.id)) ?? null
}

/** Simulated hours per round: round n is at n × this (the world's `round_hours`, 4). */
export const ROUND_HOURS = world.round_hours

const names = new Map(world.snapshot.entities.map((e) => [e.entity_id, e]))

/**
 * The world for ``snapshotId``, or null when the world file is about another snapshot.
 * `actors` are in the file's order; `edges` are typed and directed:
 * a contract from lender to borrower, an obligation from payer to payee, a shared exposure from
 * each party to the venue, and public prices from the market-maker to the treasury the world
 * is about (the other actors read the same prices; the edge stands for the feed, not a transfer).
 */
export function worldFor (snapshotId) {
  if (!snapshotId || snapshotId !== world.snapshot.snapshot_id) return null
  const actors = world.actors.map((a) => ({
    id: a.actor_id,
    label: names.get(a.actor_id)?.name?.replace(/ \(synthetic\)$/, '') ?? a.actor_id,
    role: a.role,
    objective: a.objective,
    sees: a.sees,
    tools: a.tools
  }))
  const ids = new Set(actors.map((a) => a.id))
  const edges = []
  for (const c of world.snapshot.contracts) {
    edges.push({ id: `contract:${c.contract_id}`, from: c.lender, to: c.borrower, type: 'financial',
      label: `${c.contract_id} · ${c.kind.replace(/_/g, ' ')}`, ref: c.contract_id })
  }
  for (const o of world.snapshot.obligations) {
    if (!ids.has(o.kind)) continue // the payee is an actor only when one carries the obligation's kind
    edges.push({ id: `obligation:${o.obligation_id}`, from: o.entity, to: o.kind, type: 'financial',
      label: `${o.kind} ${o.obligation_id}`, ref: o.obligation_id })
  }
  for (const e of world.snapshot.exposures) {
    for (const party of e.shared_with) {
      edges.push({ id: `exposure:${e.exposure_id}:${party}`, from: party, to: e.venue, type: 'exposure',
        label: party === 'lender' && e.account ? `exposure · ${e.account}` : `exposure · ${e.flow_id ?? e.exposure_id}`,
        ref: e.exposure_id, account: e.account ?? null, flow: e.flow_id ?? null })
    }
  }
  if (ids.has('market-maker') && ids.has('treasury')) {
    edges.push({ id: 'prices:market-maker', from: 'market-maker', to: 'treasury', type: 'information',
      label: 'public prices', ref: null })
  }
  return { snapshotId, actors, edges, epoch: world.epoch, roundHours: world.round_hours }
}

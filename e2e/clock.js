/**
 * The narrated take's clock: every beat ends at its planned end, counted from the take's start.
 *
 * Inside a beat nothing is awaited without a bound: a timeout is `budget(ms)`, cut to the time the
 * beat has left, and any other await goes through `within`. A step that stalls (a scroll the page
 * does not answer, a slow screen, an operator call) is cut at its beat's deadline, so the stall
 * shortens the beat it hit instead of pushing every later one.
 *
 * Plain CommonJS with no imports, so tests/demo/test_narrated_take_timing.py can drive it with node
 * and a virtual clock (`read` and `sleep` are passed in).
 */

const FLOOR_MS = 100 // a cut timeout is never 0, which Playwright reads as "no timeout"
const CUT = Symbol('cut')

class Clock {
  /**
   * @param {() => number} read monotonic milliseconds
   * @param {(ms: number) => Promise<void>} sleep
   */
  constructor (read, sleep) {
    this.read = read
    this.sleep = sleep
    this.zero = read()
    /** seconds from the take's start at which the beat in hand ends */
    this.deadline = Infinity
  }

  /** The take starts now: the first beat's planned 0:00. */
  start () {
    this.zero = this.read()
  }

  /** Seconds since the take's start. */
  now () {
    return (this.read() - this.zero) / 1000
  }

  /** Seconds the beat in hand has left. */
  left () {
    return this.deadline - this.now()
  }

  /** A timeout of at most `ms`, cut to the time the beat has left. */
  budget (ms) {
    return Math.max(FLOOR_MS, Math.min(ms, Math.floor(this.left() * 1000)))
  }

  /**
   * `work`'s answer, or undefined once `budget(ms)` passes first; the work is left to finish on
   * its own. A rejection is passed on.
   * @template T
   * @param {Promise<T>} work
   * @param {number} [ms]
   * @returns {Promise<T | undefined>}
   */
  async within (work, ms = Infinity) {
    const answer = await Promise.race([work, this.sleep(this.budget(ms)).then(() => CUT)])
    return answer === CUT ? undefined : answer
  }
}

/**
 * Step through the time left until `until`, one `step(fraction)` a second, each cut at a second;
 * a step the page does not answer costs that second, never the beat.
 * @param {Clock} clock
 * @param {number} until
 * @param {(fraction: number) => Promise<unknown>} step
 */
async function hold (clock, until, step) {
  const steps = Math.max(1, Math.ceil(until - clock.now()))
  for (let i = 1; i <= steps && clock.now() < until; i++) {
    await clock.within(step(i / steps), Math.min(1000, (until - clock.now()) * 1000))
    await clock.sleep(Math.max(0, Math.min(1000, (until - clock.now()) * 1000)))
  }
}

/**
 * Play each beat against its own deadline, its planned end: `play(beat)` returns the beat's record,
 * the clock waits out what is left of the beat, and `after(record)` gets it with `left` set.
 * @template {{ end: number }} B
 * @param {Clock} clock
 * @param {B[]} beats
 * @param {(beat: B) => Promise<object | undefined>} play
 * @param {(record: object) => void} [after]
 */
async function runBeats (clock, beats, play, after = () => {}) {
  for (const beat of beats) {
    clock.deadline = beat.end
    const record = (await play(beat)) ?? {}
    if (clock.left() > 0) await clock.sleep(clock.left() * 1000)
    record.left = clock.now()
    after(record)
  }
  clock.deadline = Infinity
}

module.exports = { Clock, hold, runBeats }

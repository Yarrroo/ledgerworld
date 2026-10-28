// Unit tests never reach a network: a request no test stubbed fails at once as unreachable,
// instead of trying a server that may or may not be listening on this machine.
globalThis.fetch = async (url) => {
  throw new TypeError(`unit tests are offline: no fetch stub for ${url}`)
}

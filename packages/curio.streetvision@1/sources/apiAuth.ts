/**
 * Headers that identify the signed-in user to the Street Vision backend.
 *
 * Every route in this package requires a signed-in caller, and resolves
 * per-account state from it: `/models/search` and `/inference/run` resolve the
 * HuggingFace token that unlocks gated models, `/inference/results/<id>`
 * answers only the account that started the job, and `/inference/overlay/<id>`
 * reads that account's overlay cache. Every request here sends this header.
 *
 * `getAuthToken` is a getter on `window.curio` rather than a value because this
 * bundle evaluates once at boot, before sign-in.
 */
export function authHeaders(): Record<string, string> {
  const get = typeof window !== 'undefined' && (window as any).curio?.getAuthToken;
  const token = typeof get === 'function' ? get() : undefined;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

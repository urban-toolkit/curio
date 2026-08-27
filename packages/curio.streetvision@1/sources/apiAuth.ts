/**
 * Headers that identify the signed-in user to the Street Vision backend.
 *
 * Every route in this package resolves per-account state from the caller:
 * `/models/search` and `/inference/run` resolve the HuggingFace token that
 * unlocks gated models (granted per account, against a licence that account
 * accepted), and `/inference/overlay/<id>` resolves which user's overlay cache
 * to read. Without this header the backend falls back to the shared guest key,
 * so a signed-in user's own token never takes effect and their overlays are
 * looked up in somebody else's directory.
 *
 * `getAuthToken` is a getter on `window.curio` rather than a value because this
 * bundle evaluates once at boot, before sign-in.
 */
export function authHeaders(): Record<string, string> {
  const get = typeof window !== 'undefined' && (window as any).curio?.getAuthToken;
  const token = typeof get === 'function' ? get() : undefined;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

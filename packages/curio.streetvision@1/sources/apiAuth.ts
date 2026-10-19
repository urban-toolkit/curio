/** Resolve the current Curio session header when making backend requests. */
export function authHeaders(): Record<string, string> {
  const get = typeof window !== 'undefined' && (window as any).curio?.getAuthToken;
  const token = typeof get === 'function' ? get() : undefined;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

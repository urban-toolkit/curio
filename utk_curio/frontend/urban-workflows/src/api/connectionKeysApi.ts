import { apiFetch } from "../utils/authApi";

/**
 * dev/116 (DEC-074): the per-user connection keys a data-loading node reaches
 * ONLY as `curio_secret("<name>")`. This module writes a key once (masked,
 * never read back) and lists refs; no response ever carries a value. Kept
 * light on purpose (dev/91 lesson): nothing here drags the vega-heavy
 * agentsApi into a settings screen.
 */
export interface ConnectionKeyRef {
  name: string;
  host: string;
  /** "code" (the node's code decides) | "query:<param>" | "header:<Name>". */
  delivery: string;
  /** The one line of node code that reaches this key. */
  use: string;
  createdAt: number;
  lastUsedAt: number | null;
}

export interface ConnectionKeyPut {
  host: string;
  value: string;
  delivery?: string;
  /** Required to re-bind an existing name to a different host (409 otherwise). */
  replace?: boolean;
}

const BASE = "/api/users/me/connection-keys";

export const connectionKeysApi = {
  list(): Promise<{ keys: ConnectionKeyRef[] }> {
    return apiFetch(BASE);
  },
  put(name: string, body: ConnectionKeyPut): Promise<{ key: ConnectionKeyRef }> {
    return apiFetch(`${BASE}/${encodeURIComponent(name)}`, {
      method: "PUT",
      body: JSON.stringify(body),
    });
  },
  remove(name: string): Promise<{ deleted: string }> {
    return apiFetch(`${BASE}/${encodeURIComponent(name)}`, { method: "DELETE" });
  },
  suggestName(host: string): Promise<{ name: string }> {
    return apiFetch(`${BASE}/suggest-name?host=${encodeURIComponent(host)}`);
  },
};

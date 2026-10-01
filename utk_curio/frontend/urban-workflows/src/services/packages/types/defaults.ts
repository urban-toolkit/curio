/**
 * The account's always-installed set: the global install response and its per-project rows.
 *
 * The packages service layer (memo dev/143, F1) — the twin of `services/datasetCatalog`
 * and `services/agents`. Components render; this layer owns transport, the hooks over it
 * (F2–F3) and pure logic.
 */

/** Per-project result row in a global (defaults) install response. */
export interface DefaultsInstallProjectResult {
  id: string;
  ok: boolean;
  alreadyPresent?: boolean;
  error?: string;
}

export interface DefaultsInstallResponse {
  /** New user-defaults list after the install. */
  packages: string[];
  /**
   * ``{library: reason}`` for declared python deps that installed but cannot
   * be imported - the same claim the drawer and the dataflow loader make.
   */
  importErrors?: Record<string, string>;
  /** Per-project apply results so the UI can surface partial failures. */
  projects: DefaultsInstallProjectResult[];
}

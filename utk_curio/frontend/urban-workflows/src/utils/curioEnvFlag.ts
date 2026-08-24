const TRUE_VALUES = new Set(["1", "true", "yes", "on"]);
const FALSE_VALUES = new Set(["0", "false", "no", "off"]);

/** Parse ``1``/``true``/``yes``/``on`` vs ``0``/``false``/``no``/``off`` (see backend ``_env_flag``). */
export function readCurioEnvFlag(
  raw: string | undefined,
  defaultValue: boolean,
): boolean {
  if (raw == null || !String(raw).trim()) return defaultValue;
  const value = String(raw).trim().toLowerCase();
  if (TRUE_VALUES.has(value)) return true;
  if (FALSE_VALUES.has(value)) return false;
  return defaultValue;
}

/**
 * Global default for the per-node **Save** toggle (catalog parquet on run).
 * OFF by default (mirrors backend ``CURIO_DEFAULT_SAVE_NODE_OUTPUT``): saving a
 * node's output as a Computed dataset is opt-in per node. Set
 * ``CURIO_DEFAULT_SAVE_NODE_OUTPUT=1`` (or ``true``/``yes``/``on``) to save every
 * node's output instead.
 *
 * This is only the build-time seed. ``FlowProvider`` overrides it from
 * ``/api/config/public``'s ``default_save_node_output``, which is authoritative;
 * keeping the two in step just avoids the toggle flashing the wrong state before
 * that fetch lands.
 */
export function defaultSaveOutputDatasetFromEnv(): boolean {
  return readCurioEnvFlag(process.env.CURIO_DEFAULT_SAVE_NODE_OUTPUT, false);
}

import { SupportedType } from "../constants";

/**
 * The port data types a node may declare, in the order the settings dialog
 * offers them.
 *
 * One authority for a vocabulary that had two independent derivations: the
 * settings dialog built its own list from ``Object.values(SupportedType)``,
 * while ``packagesClient.asSupportedTypes`` built a separate ``Set`` to filter
 * incoming manifests. Nothing kept them in step, and the dialog's field was
 * free text anyway -- so a typo passed the editor, was silently dropped on the
 * way in, and the port lost a type with no error anywhere (#219).
 *
 * The set is CLOSED. ``ConnectionValidator`` compares these values directly, so
 * a type outside the enum can never match anything and a package declaring one
 * would have ports nothing could connect to. That is why the control is a
 * ``<select>`` rather than a combobox with a custom-value escape hatch.
 */
export const SUPPORTED_PORT_TYPES: readonly SupportedType[] = Object.freeze(
  Object.values(SupportedType),
);

/** Is *value* one of the declarable port types? */
export function isSupportedPortType(value: string): value is SupportedType {
  return (SUPPORTED_PORT_TYPES as readonly string[]).includes(value);
}

/**
 * Normalize whatever a draft is carrying into a list of port types.
 *
 * Tolerates the legacy comma-separated STRING that ``PortDraft.types`` used to
 * be, so a config persisted on a canvas node before #219 still opens in the
 * editor instead of rendering one row whose value matches no option and shows
 * blank. Unknown values are kept, not dropped: the editor surfaces them so the
 * author can see and fix what they wrote, which is exactly what the silent
 * filter used to prevent.
 */
export function normalizePortTypes(raw: unknown): string[] {
  const parts = Array.isArray(raw)
    ? raw
    : typeof raw === "string"
      ? raw.split(",")
      : [];
  const seen = new Set<string>();
  const out: string[] = [];
  for (const part of parts) {
    if (typeof part !== "string") continue;
    const value = part.trim();
    if (!value || seen.has(value)) continue;
    seen.add(value);
    out.push(value);
  }
  return out;
}

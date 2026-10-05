/**
 * Marks an output a Data Pool re-emits because of a selection, not because its
 * data changed.
 *
 * A selection comes back to every chart the pool feeds as a new `data.input`
 * carrying the same rows with fresh `interacted` flags. A chart only has to swap
 * those rows into the view it already has (useVega's hot reload) to highlight
 * them; rebuilding it would throw its own selection away. The tag is how the
 * canvas's redraw effect tells the two apart.
 *
 * The tag can also name the chart whose selection it is, when the flags are one
 * chart's: that chart already shows them. A Vega chart's brush is its own state
 * and the flags only recolour rows, but an Autark plot's highlight IS its
 * selection, so its own selection put back on it replaces the brush it is
 * drawing (an empty one erases it).
 *
 * Symbol keys: the object spread in `normalizeFlowInput` copies them, and
 * `JSON.stringify` never writes them, so they cannot reach a request or a saved
 * project.
 */
export const SELECTION_ECHO: unique symbol = Symbol("curio.selectionEcho");
export const SELECTION_SOURCE: unique symbol = Symbol("curio.selectionSource");

/** How an output says it is a selection coming back, and whose. */
export interface SelectionEchoOptions {
  selectionEcho?: boolean;
  /** The node whose selection the flags are, when they are one node's. */
  selectionSource?: string;
}

export function markSelectionEcho<T extends object>(output: T, source?: string): T {
  (output as any)[SELECTION_ECHO] = true;
  if (source) (output as any)[SELECTION_SOURCE] = source;
  return output;
}

export function isSelectionEcho(input: unknown): boolean {
  return !!input && typeof input === "object" && (input as any)[SELECTION_ECHO] === true;
}

const isBundle = (value: unknown): value is { data: unknown[] } =>
  !!value && typeof value === "object" && (value as any).dataType === "outputs" && Array.isArray((value as any).data);

/**
 * Which input circle of a node *input* brings a selection back on, or null.
 * One input is circle 0. Several inputs arrive as one bundle, rebuilt on
 * every delivery, so the echo is the one circle whose value changed since
 * *previous*, and only when that value is an echo (#662).
 */
export function echoedCircle(input: unknown, previous: unknown): number | null {
  if (isSelectionEcho(input)) return 0;
  if (!isBundle(input) || !isBundle(previous) || input.data.length !== previous.data.length) return null;
  const changed = input.data.flatMap((value, circle) => (value === previous.data[circle] ? [] : [circle]));
  return changed.length === 1 && isSelectionEcho(input.data[changed[0]]) ? changed[0] : null;
}

/** The node whose own selection *input* brings back, if it is one node's. */
export function selectionEchoSource(input: unknown): string | undefined {
  if (!isSelectionEcho(input)) return undefined;
  const source = (input as any)[SELECTION_SOURCE];
  return typeof source === "string" ? source : undefined;
}

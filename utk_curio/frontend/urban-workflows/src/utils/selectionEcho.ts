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
 * A symbol key: the object spread in `normalizeFlowInput` copies it, and
 * `JSON.stringify` never writes it, so it cannot reach a request or a saved
 * project.
 */
export const SELECTION_ECHO: unique symbol = Symbol("curio.selectionEcho");

export function markSelectionEcho<T extends object>(output: T): T {
  (output as any)[SELECTION_ECHO] = true;
  return output;
}

export function isSelectionEcho(input: unknown): boolean {
  return !!input && typeof input === "object" && (input as any)[SELECTION_ECHO] === true;
}

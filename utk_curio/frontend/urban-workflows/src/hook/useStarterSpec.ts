import { useEffect, useRef, useState } from "react";
import type { GrammarInput } from "../utils/grammarInput";
import { isEmptySpecBuffer } from "../utils/starterSpec";

/**
 * A starter spec chosen from the arriving input, for an editor that is still
 * empty. The Vega-Lite and Autark nodes fill themselves this one way; only the
 * ladder that picks the spec is each node's own.
 *
 * Deliberately narrow:
 * - only while the editor is empty now, typing included, so it never replaces
 *   something the user has started;
 * - only once per node per session;
 * - only after an input has actually arrived: an edge alone carries no schema;
 * - never over something written into the node from outside (`data.defaultCode`:
 *   an agent's write, a dataset drop), and it steps aside when one lands later.
 *
 * It never runs the node. `useMonacoExternalValue` no-ops when the value is
 * unchanged, so offering it again is safe for the cursor and undo stack.
 */
export function useStarterSpec(opts: {
  input: unknown;
  /** What the editor holds now. */
  buffer: string | null | undefined;
  /** What was written into the node from outside, if anything. */
  written: string | null | undefined;
  /** Read the input, from the preview where that is enough. */
  read: (input: unknown) => Promise<GrammarInput>;
  /** The node's ladder: the spec text for this input, or null. */
  choose: (read: GrammarInput) => string | null;
}): string | undefined {
  const { input, buffer, written, read, choose } = opts;
  const [generated, setGenerated] = useState<string | null>(null);
  const filledRef = useRef(false);
  const writtenElsewhere = !isEmptySpecBuffer(written);
  const bufferIsEmpty = isEmptySpecBuffer(buffer) && generated == null;

  useEffect(() => {
    if (filledRef.current || !bufferIsEmpty || writtenElsewhere) return;
    if (input == null || input === "") return;
    let cancelled = false;
    read(input)
      .then((result) => {
        if (cancelled) return;
        const text = choose(result);
        if (text) {
          filledRef.current = true;
          setGenerated(text);
        }
      })
      .catch(() => {
        // A default is a convenience. Failing to pick one leaves the editor
        // empty, which is the honest state anyway.
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [input, bufferIsEmpty, writtenElsewhere]);

  return writtenElsewhere ? undefined : generated ?? undefined;
}

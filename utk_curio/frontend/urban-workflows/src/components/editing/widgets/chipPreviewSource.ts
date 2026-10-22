/**
 * What a node's chip previews read (#662), for the one Curio tooltip.
 *
 * The TooltipLayer draws a tooltip's content in a portal of its own, outside
 * the node's tree, so what a preview shows cannot reach it through props or a
 * context once it is registered. A node holds one source instead, which keeps
 * its identity: its snapshot (the node's scope, its language and what has
 * been read for its chips) is replaced as reads come back, and a preview on
 * screen follows it (ChipPreviewTip). A preview asks the source to read what
 * its chip shows as it first shows, so a pointer that only passes over a chip
 * reads nothing.
 */
import { createContext, useLayoutEffect, useMemo, useRef } from "react";
import type { CodeLanguage, ReferenceScope } from "../../../utils/references/codeReferences";
import type { ChipPreviewData } from "./ChipPreview";

export interface ChipPreviewSnapshot {
  scope: ReferenceScope;
  language: CodeLanguage;
  data: ChipPreviewData;
}

export interface ChipPreviewSource {
  get: () => ChipPreviewSnapshot;
  subscribe: (listener: () => void) => () => void;
  /** Read what the chip *inner* shows: its input's rows, its selection's. */
  load: (inner: string) => void;
}

/** The source of the header a tag sits in, which its preview reads. */
export const ChipPreviewContext = createContext<ChipPreviewSource | null>(null);

/**
 * A source that keeps its identity while *snapshot* changes: a preview on
 * screen follows each new one. *load* reads what a chip shows.
 */
export function useChipPreviewSource(snapshot: ChipPreviewSnapshot, load: (inner: string) => void): ChipPreviewSource {
  const held = useRef<{ snapshot: ChipPreviewSnapshot; load: (inner: string) => void; listeners: Set<() => void> } | null>(
    null,
  );
  if (!held.current) held.current = { snapshot, load, listeners: new Set() };
  held.current.load = load;
  const source = useMemo<ChipPreviewSource>(() => {
    const at = held.current!;
    return {
      get: () => at.snapshot,
      subscribe: (listener) => {
        at.listeners.add(listener);
        return () => {
          at.listeners.delete(listener);
        };
      },
      load: (inner) => at.load(inner),
    };
  }, []);
  useLayoutEffect(() => {
    const at = held.current!;
    if (at.snapshot === snapshot) return;
    at.snapshot = snapshot;
    for (const listener of [...at.listeners]) listener();
  }, [snapshot]);
  return source;
}

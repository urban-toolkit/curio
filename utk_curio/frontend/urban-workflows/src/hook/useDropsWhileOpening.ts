/**
 * What is dropped on the canvas while the dataflow its route names is still
 * opening, kept until the canvas has opened.
 *
 * ProjectLoader fills the canvas once the server answers, and that answer is
 * also what says whose dataflow it is (`viewerMode`); the dataflow's room
 * names this tab's role apart from it, and either can come first. A drop made
 * before both was made on a canvas the load then replaced, or the way an
 * owner's tab makes it: an invited editor's file was refused as the dataflow
 * still opening. So a drop made meanwhile is kept, as it was read during the
 * drop, and handed to *land* once the canvas has opened, the canvas as it is
 * then: an owner's drop is made as an owner's, an editor's as an editor's.
 *
 * A drop on a dataflow that could not be opened is let go: the load's own
 * error says why, once. One on a canvas that opens read-only is let go by
 * *land*, as every drop there is.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import type { ProjectLoadState } from "../components/projectLoadState";
import type { RoomRole } from "../providers/collab/participants";
import { PROJECT_LOAD_WAIT_MS } from "../registry/projectPackagesStore";

/** Where the canvas is: still opening, open, or never to open. */
export type OpeningPhase = "opening" | "open" | "failed";

/** How long the canvas of another account's dataflow waits for the room to
 *  name this tab's role once the dataflow is in, as long as a save waits for a
 *  load; then what was dropped meanwhile goes the way of a read-only canvas's
 *  drops. */
export const ROLE_WAIT_MS = PROJECT_LOAD_WAIT_MS;

export interface CanvasOpening {
  /** The load of the dataflow the route names (`useProjectLoadState`). */
  load: ProjectLoadState;
  /** Whose dataflow the load says it is: `shared` for another account's. */
  viewerMode: "owner" | "shared" | undefined;
  /** This tab's role, once the dataflow's room has named it. */
  roomRole: RoomRole | null | undefined;
}

/** Where the canvas is. Another account's dataflow is open once the room has
 *  named this tab's role too, or has not within {@link ROLE_WAIT_MS}. */
export function openingPhase(
  { load, viewerMode, roomRole }: CanvasOpening,
  roleWaitOver = false,
): OpeningPhase {
  if (load === "loading") return "opening";
  if (load === "failed") return "failed";
  if (load === "loaded" && viewerMode === "shared" && roomRole == null && !roleWaitOver) return "opening";
  return "open";
}

/**
 * Returns *keep*: while the canvas is opening, it keeps a drop and answers
 * true; once the canvas is open, it answers false, and the drop is made at
 * once. Kept drops are handed to the *land* of the render the canvas opened
 * in, in the order they were made, after that render's commit: the canvas
 * then holds the dataflow, so what a drop adds comes after it.
 */
export function useDropsWhileOpening<T>(
  opening: CanvasOpening,
  land: (drop: T) => void,
): (drop: T) => boolean {
  const waitsForRole =
    opening.load === "loaded" && opening.viewerMode === "shared" && opening.roomRole == null;
  const [roleWaitOver, setRoleWaitOver] = useState(false);
  useEffect(() => {
    setRoleWaitOver(false);
    if (!waitsForRole) return undefined;
    const timer = setTimeout(() => setRoleWaitOver(true), ROLE_WAIT_MS);
    return () => clearTimeout(timer);
  }, [waitsForRole]);

  const phase = openingPhase(opening, roleWaitOver);
  const phaseRef = useRef(phase);
  phaseRef.current = phase;
  const landRef = useRef(land);
  landRef.current = land;
  const keptRef = useRef<T[]>([]);

  useEffect(() => {
    if (phase === "opening") return;
    const kept = keptRef.current;
    keptRef.current = [];
    if (phase === "failed") return;
    for (const drop of kept) landRef.current(drop);
  }, [phase]);

  return useCallback((drop: T) => {
    if (phaseRef.current !== "opening") return false;
    keptRef.current.push(drop);
    return true;
  }, []);
}

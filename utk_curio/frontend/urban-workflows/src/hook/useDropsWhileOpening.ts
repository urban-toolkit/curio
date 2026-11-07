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
 * A load that brings nodes frames them, a frame or more after it lands, so
 * the canvas has opened only once that view is set. Until then the drop was
 * made over a canvas that showed none of the dataflow: *place* puts what was
 * kept where it goes in the view the canvas now shows.
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
  /** Whether the canvas's fit of the nodes a load brought is still to be set
   *  (`loadFitPending`). */
  framing?: boolean;
}

/** Where the canvas is. Another account's dataflow is open once the room has
 *  named this tab's role too, or has not within {@link ROLE_WAIT_MS}. A
 *  dataflow whose load brought nodes is open once their fit is set; a fit
 *  after the canvas has *opened* (a version put back, a merge) keeps nothing. */
export function openingPhase(
  { load, viewerMode, roomRole, framing }: CanvasOpening,
  roleWaitOver = false,
  opened = false,
): OpeningPhase {
  if (load === "loading") return "opening";
  if (load === "failed") return "failed";
  if (load === "loaded" && viewerMode === "shared" && roomRole == null && !roleWaitOver) return "opening";
  if (load === "loaded" && framing && !opened) return "opening";
  return "open";
}

/**
 * Returns *keep*: while the canvas is opening, it keeps a drop and answers
 * true; once the canvas is open, it answers false, and the drop is made at
 * once. Kept drops are handed, in the order they were made, through *place*
 * when given, to the *land* of the render the canvas opened in, after that
 * render's commit: the canvas then holds the dataflow, so what a drop adds
 * comes after it. After a fit, they land on the next frame, once the fit's
 * view is set: React Flow sets a view through a d3 transition, which moves on
 * the frame after it was asked for, before any frame asked for later.
 */
export function useDropsWhileOpening<T>(
  opening: CanvasOpening,
  land: (drop: T) => void,
  place?: (kept: T[]) => T[],
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

  // Whether the canvas has opened since the dataflow came in, and whether it
  // waited for the fit of the nodes the load brought.
  const openedRef = useRef(false);
  const fittedRef = useRef(false);
  useEffect(() => {
    if (opening.load !== "loaded") {
      openedRef.current = false;
      fittedRef.current = false;
    } else if (opening.framing && !openedRef.current) {
      fittedRef.current = true;
    }
  }, [opening.load, opening.framing]);

  const phase = openingPhase(opening, roleWaitOver, openedRef.current);
  const phaseRef = useRef(phase);
  phaseRef.current = phase;
  const landRef = useRef(land);
  landRef.current = land;
  const placeRef = useRef(place);
  placeRef.current = place;
  const keptRef = useRef<T[]>([]);
  // Kept drops wait for their frame: one made meanwhile waits with them, so
  // they land in the order they were made.
  const awaitingFrameRef = useRef(false);

  useEffect(() => {
    if (phase === "opening") return undefined;
    if (opening.load === "loaded") openedRef.current = true;
    if (phase === "failed") {
      keptRef.current = [];
      return undefined;
    }
    const landKept = () => {
      awaitingFrameRef.current = false;
      const kept = keptRef.current;
      keptRef.current = [];
      if (kept.length === 0) return;
      const placed = placeRef.current ? placeRef.current(kept) : kept;
      for (const drop of placed) landRef.current(drop);
    };
    if (!fittedRef.current || keptRef.current.length === 0) {
      landKept();
      return undefined;
    }
    awaitingFrameRef.current = true;
    const frame = window.requestAnimationFrame(landKept);
    return () => {
      awaitingFrameRef.current = false;
      window.cancelAnimationFrame(frame);
    };
  }, [phase, opening.load]);

  return useCallback((drop: T) => {
    if (phaseRef.current !== "opening" && !awaitingFrameRef.current) return false;
    keptRef.current.push(drop);
    return true;
  }, []);
}

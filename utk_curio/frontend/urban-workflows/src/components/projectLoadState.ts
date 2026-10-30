/**
 * How far the load of the dataflow the route names has got, which
 * ProjectLoader gives everything under it.
 *
 * In a module of its own, so the canvas and its top bar read it without
 * ProjectLoader and what it loads with.
 */
import { createContext, useContext } from "react";

/** How far the load has got, for a page that has to say which state it is in. */
export type ProjectLoadState = "idle" | "loading" | "loaded" | "failed";

export const ProjectLoadStateContext = createContext<ProjectLoadState>("idle");

/**
 * The load's progress.
 *
 * The dashboard needs it to tell three things apart that all render as an empty
 * page: still loading, loaded with nothing pinned, and could not be opened. The
 * canvas reads it while the dataflow is opening: its title says so, and what is
 * dropped on it waits for the dataflow (`useDropsWhileOpening`).
 */
export function useProjectLoadState(): ProjectLoadState {
  return useContext(ProjectLoadStateContext);
}

/** The canvas title while the dataflow the route names is still opening,
 *  whose name is not known yet. */
export const OPENING_TITLE = "Opening dataflow…";

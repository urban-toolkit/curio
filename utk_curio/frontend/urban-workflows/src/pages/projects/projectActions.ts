/**
 * What can be done to a project, in one place.
 *
 * The projects page had two surfaces rendering hand-written action lists, and
 * only one of them consulted ``archived_at``: the detail drawer offered Archive
 * OR Delete depending on state, while the right-click menu hardcoded five items
 * and offered both to everything. So the same project simultaneously said "you
 * may only archive this" and "you may delete this outright" (#221).
 *
 * Nothing structural made them agree, which is why they drifted. Both now
 * render this list, so a change reaches both or neither. Keep it that way: any
 * new action belongs here, not on one surface.
 */

export type ProjectActionId =
  | "open"
  | "rename"
  | "duplicate"
  | "delete";

export interface ProjectAction {
  id: ProjectActionId;
  label: string;
  /** Needs a confirmation, and is styled as a way out rather than a way on. */
  destructive?: boolean;
}

/** The one property of a project that changes what may be done to it. */
export interface ProjectActionState {
  /** Seeded from ``docs/examples/`` - Curio put it there, the user did not. */
  isExample?: boolean;
}

/**
 * The actions available for a project, in the order they are shown.
 *
 * Destructive last, matching the order the catalogs already use — the way out
 * is offered after every way on.
 *
 * Archive used to make this conditional, and was removed (#261) because it
 * never cleared — no restore route, no unarchive action — so it was a second
 * permanent state that merely read as the cautious one next to deletion.
 * "Delete" dropped its "forever" along with it: with no softer-sounding sibling
 * to contrast against, the plain verb plus the ``Permanently delete "…"?``
 * confirmation carries it.
 *
 * One state remains, and it subtracts rather than adds: an example dataflow
 * offers no Delete. The same rule the Data Catalog has had since "hide delete
 * for anything that came from the shared catalog" - what Curio seeded is yours
 * to open, rename and edit, but not to remove. It reads as fussy until you
 * notice there is no way back: since #270 the per-account marker means a
 * deleted example is never seeded again, so the mis-click was permanent. The
 * server refuses the same request, for the callers that never see this list.
 */
export function projectActions(state: ProjectActionState = {}): ProjectAction[] {
  return [
    { id: "open", label: "Open" },
    { id: "rename", label: "Rename" },
    { id: "duplicate", label: "Duplicate" },
    ...(state.isExample
      ? []
      : [{ id: "delete" as const, label: "Delete", destructive: true }]),
  ];
}

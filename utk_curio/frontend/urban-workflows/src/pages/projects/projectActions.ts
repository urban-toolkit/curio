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

/**
 * The actions available for a project, in the order they are shown.
 *
 * Destructive last, matching the order the catalogs already use — the way out
 * is offered after every way on.
 *
 * Takes no state: every project offers the same set. Archive used to make this
 * conditional, and was removed (#261) because it never cleared — no restore
 * route, no unarchive action — so it was a second permanent state that merely
 * read as the cautious one next to deletion. "Delete" dropped its "forever"
 * along with it: with no softer-sounding sibling to contrast against, the plain
 * verb plus the ``Permanently delete "…"?`` confirmation carries it.
 */
export function projectActions(): ProjectAction[] {
  return [
    { id: "open", label: "Open" },
    { id: "rename", label: "Rename" },
    { id: "duplicate", label: "Duplicate" },
    { id: "delete", label: "Delete", destructive: true },
  ];
}

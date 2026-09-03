/**
 * What can be done to a project, in one place.
 *
 * The projects page had two surfaces rendering hand-written action lists, and
 * only one of them consulted ``archived_at``: the detail drawer offered Archive
 * OR Delete forever depending on state, while the right-click menu hardcoded
 * five items and offered both to everything. So the same project simultaneously
 * said "you may only archive this" and "you may delete this outright" (#221).
 *
 * Nothing structural made them agree, which is why they drifted. Both now
 * render this list, so a change reaches both or neither.
 */

export type ProjectActionId =
  | "open"
  | "rename"
  | "duplicate"
  | "archive"
  | "restore"
  | "delete";

export interface ProjectAction {
  id: ProjectActionId;
  label: string;
  /** Needs a confirmation, and is styled as a way out rather than a way on. */
  destructive?: boolean;
}

export interface ProjectActionState {
  /** ``archived_at`` — set once the project has been archived. */
  archived: boolean;
}

/**
 * The actions available for a project in *state*, in the order they are shown.
 *
 * Destructive last, matching the order the catalogs already use — the way out
 * is offered after every way on.
 *
 * "Delete forever" is offered whether or not the project is archived. Hiding it
 * until after archiving made the drawer look like archiving was the only thing
 * you could do, while the context menu offered deletion anyway; the archive
 * step was never a safety mechanism, just an inconsistency. The confirm dialog
 * is what makes deletion deliberate.
 */
export function projectActions(state: ProjectActionState): ProjectAction[] {
  const actions: ProjectAction[] = [
    { id: "open", label: "Open" },
    { id: "rename", label: "Rename" },
    { id: "duplicate", label: "Duplicate" },
  ];
  // Archiving something already archived is a no-op the UI should not offer.
  // There is no restore route yet, so an archived project simply loses the
  // action rather than gaining a "Restore" that would not work.
  if (!state.archived) {
    actions.push({ id: "archive", label: "Archive" });
  }
  actions.push({ id: "delete", label: "Delete forever", destructive: true });
  return actions;
}

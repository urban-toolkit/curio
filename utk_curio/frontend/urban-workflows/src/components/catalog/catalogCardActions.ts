/**
 * What a catalog browse card offers on right-click, for each of the three
 * catalogs.
 *
 * The rule, and the only one worth remembering: a card's context menu offers
 * what that card's detail drawer offers, in the drawer's own order - the
 * primary action first, then "View details" as the way out. A right-click is a
 * shortcut into the panel, not a second vocabulary, and `projectActions` earned
 * that lesson the hard way (#221: two surfaces with hand-written lists
 * disagreed about what a project allowed).
 *
 * The catalogs differ in their primary action, which is why this is one
 * function each rather than one for all: a dataset is added to every project or
 * detached from it, an agent is imported or un-imported, a package is installed
 * and can then be updated, a Discovery Catalog source is browsed, and a
 * downloaded model can be deleted. Each builder takes the state its drawer
 * already computes, so neither surface decides anything the other cannot see.
 *
 * Publish and Unpublish are deliberately absent. They are not plain buttons in
 * the drawer: `CatalogPublishPill` puts a confirmation in front of each,
 * because both write to the whole deployment's catalog. A menu row calling the
 * handler directly would be a second, laxer path to the same write - so the
 * pill stays the only way to reach it.
 *
 * "Remove from all projects" is not `destructive`. The drawers paint it in the
 * light way-out style rather than danger red: it detaches an item and leaves
 * the catalog copy alone. Red means a real deletion, and the one browse card
 * that offers one is a downloaded model's: Delete removes its files from the
 * account, and its drawer asks first, as the menu row does.
 */

export type CatalogCardActionId =
  | "add-to-all-projects"
  | "remove-from-all-projects"
  | "update-all-projects"
  | "browse-datasets"
  | "add-by-link"
  | "delete"
  | "view-details";

export interface CatalogCardAction {
  id: CatalogCardActionId;
  label: string;
  destructive?: boolean;
}

/** Last in every menu, mirroring the drawer's secondary action. */
const VIEW_DETAILS: CatalogCardAction = { id: "view-details", label: "View details" };

export function datasetCardActions(state: {
  /** In the account-level defaults list, the only scope this page has. */
  inAllProjects: boolean;
}): CatalogCardAction[] {
  return [
    state.inAllProjects
      ? { id: "remove-from-all-projects", label: "Remove from all projects" }
      : { id: "add-to-all-projects", label: "Add to all projects" },
    VIEW_DETAILS,
  ];
}

export function agentCardActions(state: {
  /** Imported into the account, so available to every project. */
  imported: boolean;
}): CatalogCardAction[] {
  return [
    state.imported
      ? { id: "remove-from-all-projects", label: "Remove from all projects" }
      : { id: "add-to-all-projects", label: "Add to all projects" },
    VIEW_DETAILS,
  ];
}

export function packageCardActions(state: {
  /** In the defaults list for new and existing projects. */
  isInstalled: boolean;
  /** A newer version sits in the catalog than the installed one. */
  hasUpdate: boolean;
}): CatalogCardAction[] {
  // Installed and current is the one state with no primary action - the drawer
  // renders a sentence there, not a button, and the menu has nothing to say
  // either. It is not offered as a disabled row: a greyed "Add to all projects"
  // would read as something this package refuses rather than something already
  // done.
  const primary: CatalogCardAction[] = !state.isInstalled
    ? [{ id: "add-to-all-projects", label: "Add to all projects" }]
    : state.hasUpdate
      ? [{ id: "update-all-projects", label: "Update all projects" }]
      : [];
  return [...primary, VIEW_DETAILS];
}

export function discoverySourceCardActions(state: {
  /** Searchable by this account: `unsearchableReason` found nothing. */
  browsable: boolean;
  /** A link-only source (Direct URL): its page takes a link instead. */
  byLink?: boolean;
}): CatalogCardAction[] {
  // A source that cannot be searched gets a sentence in the drawer's primary
  // slot, not a button, so the menu offers no primary either - the same rule
  // as an installed, current package. A link-only source has a page to open
  // all the same: the one that takes the link.
  const primary: CatalogCardAction[] = state.byLink
    ? [{ id: "add-by-link", label: "Add by link" }]
    : state.browsable
      ? [{ id: "browse-datasets", label: "Browse datasets" }]
      : [];
  return [...primary, VIEW_DETAILS];
}

export function modelCardActions(state: {
  /** Downloaded into this account; a shipped model cannot be deleted. */
  deletable: boolean;
}): CatalogCardAction[] {
  // A shipped model has no action at all, so the menu offers only its details,
  // as for an installed, current package. A downloaded one can be deleted,
  // which is a real deletion and is painted as one.
  const primary: CatalogCardAction[] = state.deletable
    ? [{ id: "delete", label: "Delete", destructive: true }]
    : [];
  return [...primary, VIEW_DETAILS];
}

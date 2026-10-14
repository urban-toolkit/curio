/**
 * One definition of what a catalog browse card offers on right-click (#285).
 *
 * The Node, Data and Agent Catalogs used to answer a right-click with the
 * browser's own menu - Back, Reload, View Page Source - while the projects page
 * next door opened an app menu on an identically shaped card. These builders
 * are the catalogs' half of the fix, and `projectActions` is the projects half;
 * both exist so a card's menu and its detail drawer cannot drift apart the way
 * the projects page's two surfaces once did (#221).
 */
import * as cardActions from "../../components/catalog/catalogCardActions";
import {
  agentCardActions,
  datasetCardActions,
  discoverySourceCardActions,
  packageCardActions,
  scenarioCardActions,
} from "../../components/catalog/catalogCardActions";

describe("catalog card actions", () => {
  test("a dataset outside the defaults list is offered the way in", () => {
    expect(datasetCardActions({ inAllProjects: false }).map((a) => a.id)).toEqual([
      "add-to-all-projects",
      "view-details",
    ]);
  });

  test("a dataset already in every project is offered the way out instead", () => {
    // Never both: the drawer's primary slot holds one button, and the menu
    // mirrors it.
    expect(datasetCardActions({ inAllProjects: true }).map((a) => a.id)).toEqual([
      "remove-from-all-projects",
      "view-details",
    ]);
  });

  test("an agent follows the same two states", () => {
    expect(agentCardActions({ imported: false }).map((a) => a.id)).toEqual([
      "add-to-all-projects",
      "view-details",
    ]);
    expect(agentCardActions({ imported: true }).map((a) => a.id)).toEqual([
      "remove-from-all-projects",
      "view-details",
    ]);
  });

  test("an uninstalled package offers the install", () => {
    expect(
      packageCardActions({ isInstalled: false, hasUpdate: false }).map((a) => a.id),
    ).toEqual(["add-to-all-projects", "view-details"]);
  });

  test("an installed package with a newer catalog version offers the update", () => {
    expect(
      packageCardActions({ isInstalled: true, hasUpdate: true }).map((a) => a.id),
    ).toEqual(["update-all-projects", "view-details"]);
  });

  test("an installed, current package offers no primary action at all", () => {
    // The drawer renders a sentence in that slot, not a button. A greyed-out
    // "Add to all projects" would read as a refusal rather than as something
    // already done.
    expect(
      packageCardActions({ isInstalled: true, hasUpdate: false }).map((a) => a.id),
    ).toEqual(["view-details"]);
  });

  test("a Discovery Catalog source offers the browse, then its details", () => {
    expect(discoverySourceCardActions({ browsable: true }).map((a) => a.id)).toEqual([
      "browse-datasets",
      "view-details",
    ]);
  });

  test("a source that cannot be searched offers only its details", () => {
    // The drawer shows why in that slot, not a button, as for a current package.
    expect(discoverySourceCardActions({ browsable: false }).map((a) => a.id)).toEqual([
      "view-details",
    ]);
  });

  test("a link-only source offers Add by link, then its details", () => {
    // Its page takes the link, so it has a page to open even though it has
    // nothing to browse (#439).
    expect(
      discoverySourceCardActions({ browsable: false, byLink: true }).map((a) => a.id),
    ).toEqual(["add-by-link", "view-details"]);
  });

  test("a model is a package: its card offers a package's actions, and no Delete of its own", () => {
    // The Model Catalog is the Node Catalog's page over model packages, so a
    // model's menu is the package one: Add to all projects, Update, then its
    // details. A model leaves the account as a node package does, through
    // Remove in each dataflow, never through a Delete of its own.
    expect((cardActions as Record<string, unknown>).modelCardActions).toBeUndefined();
    for (const state of [
      { isInstalled: false, hasUpdate: false },
      { isInstalled: true, hasUpdate: true },
      { isInstalled: true, hasUpdate: false },
    ]) {
      const ids: string[] = packageCardActions(state).map((a) => a.id);
      expect(ids).not.toContain("delete");
    }
  });

  test("a scenario offers its source project, then its details", () => {
    // Read-only in the catalog: it changes when its project is edited, so the
    // one action is opening that project. Nothing renames or deletes it here.
    expect(scenarioCardActions().map((a) => a.id)).toEqual([
      "open-source-project",
      "view-details",
    ]);
    expect(scenarioCardActions().map((a) => a.label)).toEqual([
      "Open source project",
      "View details",
    ]);
  });

  test("publishing is never a menu row", () => {
    // `CatalogPublishPill` puts a confirmation in front of Publish and
    // Unpublish because both write to the whole deployment's catalog. A menu
    // row calling the handler would be a second, laxer path to that write.
    const every = [
      ...datasetCardActions({ inAllProjects: false }),
      ...datasetCardActions({ inAllProjects: true }),
      ...agentCardActions({ imported: false }),
      ...agentCardActions({ imported: true }),
      ...packageCardActions({ isInstalled: false, hasUpdate: false }),
      ...packageCardActions({ isInstalled: true, hasUpdate: true }),
      ...discoverySourceCardActions({ browsable: true }),
      ...packageCardActions({ isInstalled: true, hasUpdate: false }),
      ...scenarioCardActions(),
    ];
    // Widened on purpose: the two ids are not in `CatalogCardActionId` at all,
    // which is half the guarantee - the other half is that no builder emits one.
    const ids: string[] = every.map((a) => a.id);
    expect(ids.some((id) => id === "publish" || id === "unpublish")).toBe(false);
  });

  test("nothing on a browse card is painted as a deletion", () => {
    // "Remove from all projects" detaches an item and leaves the catalog copy
    // alone - the drawer paints it in the light way-out style, not danger red.
    const every = [
      ...datasetCardActions({ inAllProjects: true }),
      ...agentCardActions({ imported: true }),
      ...packageCardActions({ isInstalled: true, hasUpdate: true }),
      ...discoverySourceCardActions({ browsable: true }),
      ...scenarioCardActions(),
    ];
    expect(every.every((a) => !a.destructive)).toBe(true);
  });

  test("the way out comes last on every catalog", () => {
    for (const list of [
      datasetCardActions({ inAllProjects: false }),
      agentCardActions({ imported: true }),
      packageCardActions({ isInstalled: false, hasUpdate: false }),
      discoverySourceCardActions({ browsable: true }),
      packageCardActions({ isInstalled: true, hasUpdate: true }),
      packageCardActions({ isInstalled: true, hasUpdate: false }),
      scenarioCardActions(),
    ]) {
      expect(list[list.length - 1].id).toBe("view-details");
    }
  });

  test("every action has a label", () => {
    for (const action of [
      ...datasetCardActions({ inAllProjects: false }),
      ...datasetCardActions({ inAllProjects: true }),
      ...agentCardActions({ imported: false }),
      ...packageCardActions({ isInstalled: true, hasUpdate: true }),
      ...discoverySourceCardActions({ browsable: true }),
      ...packageCardActions({ isInstalled: false, hasUpdate: false }),
      ...scenarioCardActions(),
    ]) {
      expect(action.label.trim()).not.toBe("");
    }
  });
});

/**
 * The right-click menu every browse grid now shares (#285).
 *
 * Only the projects page answered a right-click; the Node, Data and Agent
 * Catalogs let the event through to the browser, so the same gesture on the
 * same-shaped card produced an app menu on one page and Back/Reload/View Page
 * Source on the other three. The menu markup lived inline in `ProjectsList`,
 * which is why nothing else could have one without copying it.
 *
 * Two halves are checked here: the component's own behaviour, and - read from
 * disk, the established pattern in this directory for claims about what a file
 * does not contain - that all four grids actually reach for it.
 */
import fs from "fs";
import path from "path";
import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

import { CardContextMenu } from "../../components/catalog/CardContextMenu";

const SRC = path.resolve(__dirname, "../..");
const read = (rel: string) => fs.readFileSync(path.join(SRC, rel), "utf8");

const GRIDS = [
  "pages/projects/ProjectsList.tsx",
  "pages/catalog/NodeCatalogBrowse.tsx",
  "pages/dataCatalog/DataCatalogBrowse.tsx",
  "pages/agents/AgentCatalogBrowse.tsx",
];

const CARDS = [
  "pages/catalog/PackageBrowseCard.tsx",
  "pages/dataCatalog/DataCatalogBrowseCard.tsx",
  "pages/agents/AgentCatalogBrowseCard.tsx",
];

describe("CardContextMenu", () => {
  test("renders one menu item per action", () => {
    render(
      <CardContextMenu
        x={10}
        y={20}
        ariaLabel="Dataset actions"
        items={[
          { id: "add-to-all-projects", label: "Add to all projects" },
          { id: "view-details", label: "View details" },
        ]}
        onSelect={jest.fn()}
        onDismiss={jest.fn()}
      />,
    );
    const menu = screen.getByRole("menu", { name: "Dataset actions" });
    expect(
      screen.getAllByRole("menuitem").map((el) => el.textContent),
    ).toEqual(["Add to all projects", "View details"]);
    // Positioned where the event was, not where the card is.
    expect(menu).toHaveStyle({ position: "fixed", top: "20px", left: "10px" });
  });

  test("choosing an item reports the id and closes the menu", async () => {
    const onSelect = jest.fn();
    const onDismiss = jest.fn();
    render(
      <CardContextMenu
        x={0}
        y={0}
        ariaLabel="Package actions"
        items={[{ id: "view-details", label: "View details" }]}
        onSelect={onSelect}
        onDismiss={onDismiss}
      />,
    );
    await userEvent.click(screen.getByRole("menuitem", { name: "View details" }));
    expect(onSelect).toHaveBeenCalledWith("view-details");
    expect(onDismiss).toHaveBeenCalled();
  });

  test("Escape closes it", async () => {
    // The projects page's inline menu had no Escape at all. Putting the
    // dismissal rules in the component means a new surface cannot forget them.
    const onDismiss = jest.fn();
    render(
      <CardContextMenu
        x={0}
        y={0}
        ariaLabel="Agent actions"
        items={[{ id: "view-details", label: "View details" }]}
        onSelect={jest.fn()}
        onDismiss={onDismiss}
      />,
    );
    await userEvent.keyboard("{Escape}");
    expect(onDismiss).toHaveBeenCalled();
  });

  test("a click anywhere else closes it", async () => {
    const onDismiss = jest.fn();
    render(
      <>
        <button type="button">elsewhere</button>
        <CardContextMenu
          x={0}
          y={0}
          ariaLabel="Agent actions"
          items={[{ id: "view-details", label: "View details" }]}
          onSelect={jest.fn()}
          onDismiss={onDismiss}
        />
      </>,
    );
    await userEvent.click(screen.getByRole("button", { name: "elsewhere" }));
    expect(onDismiss).toHaveBeenCalled();
  });

  test("an empty action list renders nothing", () => {
    // An installed, up-to-date package with details already open has nothing
    // to offer, and an empty box hanging off the cursor is worse than the
    // browser menu it replaced.
    const { container } = render(
      <CardContextMenu
        x={0}
        y={0}
        ariaLabel="Package actions"
        items={[]}
        onSelect={jest.fn()}
        onDismiss={jest.fn()}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  test("menu rows are buttons, not clickable divs", () => {
    // They are actions; as divs they were unreachable by keyboard and
    // announced as nothing.
    render(
      <CardContextMenu
        x={0}
        y={0}
        ariaLabel="Dataflow actions"
        items={[{ id: "delete", label: "Delete", destructive: true }]}
        onSelect={jest.fn()}
        onDismiss={jest.fn()}
      />,
    );
    const row = screen.getByRole("menuitem", { name: "Delete" });
    expect(row.tagName).toBe("BUTTON");
    expect(row).toHaveStyle({ color: "var(--curio-danger)" });
  });
});

describe("every browse grid opens one", () => {
  test("all four grids render the shared menu", () => {
    for (const grid of GRIDS) {
      const tsx = read(grid);
      expect(tsx).toMatch(/<CardContextMenu\b/);
    }
  });

  test("no grid hand-rolls a menu of its own", () => {
    // The projects page's version was written inline, with its own document
    // click listener and its own item styles.
    for (const grid of GRIDS) {
      const tsx = read(grid);
      expect(tsx).not.toContain("--curio-shadow-context-menu");
      expect(tsx).not.toContain("ctxItemStyle");
    }
  });

  test("the three catalog cards accept the gesture", () => {
    for (const card of CARDS) {
      expect(read(card)).toContain("onContextMenu={onContextMenu}");
    }
  });

  test("each grid stops the browser from answering first", () => {
    for (const grid of GRIDS) {
      const tsx = read(grid);
      const handler = tsx.slice(tsx.indexOf("onContextMenu={(e) => {"));
      expect(handler).toContain("e.preventDefault();");
    }
  });
});

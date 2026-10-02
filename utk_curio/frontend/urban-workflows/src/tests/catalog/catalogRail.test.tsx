/**
 * The one rail every browse page renders (pages/catalog/CatalogRail.tsx).
 *
 * The five pages used to write their rails out by hand and had drifted: reset
 * rows on some sections only, zero-count rows on one page and not the next, and
 * section lines that showed on some pages and vanished on others. The last one
 * was a layout bug, not markup: the dividers were empty flex items that the
 * browser shrank to 0px whenever the rail was taller than the window.
 */
import fs from "fs";
import path from "path";
import React from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import "@testing-library/jest-dom";

import {
  CatalogRail,
  visibleRailSections,
  type CatalogRailSection,
} from "../../pages/catalog/CatalogRail";

const row = (label: string, count: number, active = false) => ({
  label,
  count,
  active,
  onClick: jest.fn(),
});

describe("visibleRailSections", () => {
  it("drops rows with nothing in them", () => {
    const sections: CatalogRailSection[] = [
      { key: "format", label: "By format", entries: [row("GeoJSON", 3), row("JSON", 0)] },
    ];
    expect(visibleRailSections(sections)[0].entries.map((e) => e.label)).toEqual(["GeoJSON"]);
  });

  it("keeps the selected row at zero, so a search cannot hide what filters", () => {
    const sections: CatalogRailSection[] = [
      { key: "format", label: "By format", entries: [row("GeoJSON", 0, true), row("CSV", 2)] },
    ];
    expect(visibleRailSections(sections)[0].entries.map((e) => e.label)).toEqual([
      "GeoJSON",
      "CSV",
    ]);
  });

  it("drops a section left with no rows, label and divider with it", () => {
    const sections: CatalogRailSection[] = [
      { key: "format", label: "By format", entries: [row("GeoJSON", 1)] },
      { key: "origin", label: "By origin", entries: [row("Hub", 0)] },
    ];
    expect(visibleRailSections(sections).map((s) => s.key)).toEqual(["format"]);
  });
});

describe("CatalogRail", () => {
  const renderRail = (extra: Partial<React.ComponentProps<typeof CatalogRail>> = {}) =>
    render(
      <CatalogRail
        ariaLabel="Filter things"
        all={row("All things", 5, true)}
        scope={row("In all projects", 0)}
        sections={[
          {
            key: "format",
            label: "By format",
            entries: [
              { ...row("GeoJSON", 3), value: "geojson", dotClassName: "dot_geojson" },
              row("JSON", 0),
            ],
          },
          { key: "origin", label: "By origin", entries: [row("Hub", 2)] },
        ]}
        {...extra}
      />,
    );

  it("opens with All, then the scope row, before any section", () => {
    renderRail();
    const rail = screen.getByRole("complementary", { name: "Filter things" });
    const names = within(rail)
      .getAllByRole("button")
      .map((b) => b.textContent);
    expect(names).toEqual(["All things5", "In all projects0", "GeoJSON3", "Hub2"]);
  });

  it("shows the scope row at zero: it is a scope, not a facet value", () => {
    renderRail();
    expect(screen.getByRole("button", { name: /^In all projects/ })).toHaveTextContent(
      "In all projects0",
    );
  });

  it("puts one divider and one label before each section, none before the top group", () => {
    const { container } = renderRail();
    const rail = container.querySelector("aside") as HTMLElement;
    const kids = Array.from(rail.children);
    const dividers = kids.filter((k) => k.classList.contains("railDivider"));
    const labels = kids.filter((k) => k.classList.contains("railLabel"));
    expect(labels.map((l) => l.textContent)).toEqual(["By format", "By origin"]);
    expect(dividers).toHaveLength(2);
    // The top group comes first: All, then the scope row, then a divider.
    expect(kids[0]).toHaveTextContent("All things");
    expect(kids[1]).toHaveTextContent("In all projects");
    expect(kids[2].classList.contains("railDivider")).toBe(true);
  });

  it("can open with All alone, for a catalog with no scope", () => {
    renderRail({ scope: undefined });
    expect(screen.queryByRole("button", { name: /^In all projects/ })).toBeNull();
  });

  it("says which rows are selected, and hands a click to the row", () => {
    const all = row("All things", 5, true);
    const hub = row("Hub", 2);
    render(
      <CatalogRail
        ariaLabel="Filter things"
        all={all}
        sections={[{ key: "origin", label: "By origin", entries: [hub] }]}
      />,
    );
    expect(screen.getByRole("button", { name: /^All things/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: /^Hub/ })).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(screen.getByRole("button", { name: /^Hub/ }));
    expect(hub.onClick).toHaveBeenCalledTimes(1);
    expect(all.onClick).not.toHaveBeenCalled();
  });

  it("marks each facet row with its section and value, for the e2e suite", () => {
    renderRail();
    const geojson = screen.getByRole("button", { name: /^GeoJSON/ });
    expect(geojson).toHaveAttribute("data-curio-rail-section", "format");
    expect(geojson).toHaveAttribute("data-curio-rail-value", "geojson");
    // The value defaults to the label when a row gives none.
    expect(screen.getByRole("button", { name: /^Hub/ })).toHaveAttribute(
      "data-curio-rail-value",
      "Hub",
    );
  });

  it("draws a dot only on rows that key a card colour", () => {
    renderRail();
    const geojson = screen.getByRole("button", { name: /^GeoJSON/ });
    expect(geojson.querySelector("[data-curio-rail-dot]")).toHaveClass("dot_geojson");
    expect(
      screen.getByRole("button", { name: /^Hub/ }).querySelector("[data-curio-rail-dot]"),
    ).toBeNull();
  });
});

describe("the rail's stylesheet", () => {
  const css = fs.readFileSync(
    path.resolve(__dirname, "../../pages/catalog/CatalogBrowseLayout.module.css"),
    "utf8",
  );

  it("lets nothing in the rail shrink, so a long rail keeps its section lines", () => {
    // The rail is a scrolling flex column. Without this, a rail taller than
    // the window shrinks its empty 1px dividers to nothing: the lines showed
    // on the Node, Agent and Data Lake rails and vanished on the Data and
    // Projects ones, which overflow at 1280x720.
    const rule = css.match(/\n\.categoryRail > \* \{([^}]*)\}/);
    expect(rule).not.toBeNull();
    expect((rule as RegExpMatchArray)[1]).toMatch(/flex-shrink:\s*0/);
  });
});

import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

import { ScenarioCatalogBrowse } from "../../pages/scenarios/ScenarioCatalogBrowse";
import { scenarioCatalogApi } from "../../services/scenarioCatalog/scenarioCatalogApi";
import type { ScenarioRow } from "../../services/scenarioCatalog";
import { exampleScenario, heatDetails, heatScenario } from "../_support/scenarioRows";

jest.mock("../../services/scenarioCatalog/scenarioCatalogApi", () => ({
  scenarioCatalogApi: { listCatalog: jest.fn(), getScenario: jest.fn() },
}));

const api = scenarioCatalogApi as unknown as {
  listCatalog: jest.Mock;
  getScenario: jest.Mock;
};

/** Serve the listing (narrowed by `q` on the name, as the server does) and
 *  each scenario's details, without caring about call order. */
function routeApi(rows: ScenarioRow[]) {
  api.listCatalog.mockImplementation(({ q = "" }: { q?: string } = {}) =>
    Promise.resolve({
      items: rows.filter((row) => row.name.toLowerCase().includes(q.toLowerCase())),
    }),
  );
  api.getScenario.mockImplementation((projectId: string, scenarioId: string) => {
    const row = rows.find((r) => r.project.id === projectId && r.id === scenarioId);
    return row ? Promise.resolve(heatDetails(row)) : Promise.reject(new Error("Scenario not found"));
  });
}

/** The grid's card for one scenario, by its `<project>/<scenario>` key. */
function card(key: string): HTMLElement {
  const el = document.querySelector(`.cardGrid [data-scenario-key="${key}"]`);
  if (!el) throw new Error(`no card for ${key}`);
  return el as HTMLElement;
}

const railRow = (section: string, value: string) =>
  document.querySelector(
    `[data-curio-rail-section="${section}"][data-curio-rail-value="${value}"]`,
  ) as HTMLElement;

let location = "";
const LocationProbe: React.FC = () => {
  location = useLocation().pathname;
  return null;
};

function renderPage(entry = "/catalog/scenarios") {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path="/catalog/scenarios/:projectId?/:scenarioId?" element={<ScenarioCatalogBrowse />} />
        <Route path="/dataflow/:id" element={<div>canvas page</div>} />
      </Routes>
      <LocationProbe />
    </MemoryRouter>,
  );
}

const details = () => screen.queryByRole("dialog", { name: "Scenario details" });

beforeEach(() => {
  api.listCatalog.mockReset();
  api.getScenario.mockReset();
  location = "";
});

describe("ScenarioCatalogBrowse", () => {
  test("says it is loading until the listing answers", () => {
    api.listCatalog.mockReturnValue(new Promise(() => {}));
    renderPage();
    expect(screen.getByText("Loading scenarios…")).toBeInTheDocument();
  });

  test("an account with no scenario says how to make one", async () => {
    routeApi([]);
    renderPage();
    expect(
      await screen.findByText(
        "No scenarios yet. Select nodes on a canvas and choose View > Save selection as scenario.",
      ),
    ).toBeInTheDocument();
  });

  test("a failed load surfaces the error, and Retry loads again", async () => {
    api.listCatalog
      .mockRejectedValueOnce(new Error("backend is down"))
      .mockResolvedValue({ items: [heatScenario()] });
    api.getScenario.mockResolvedValue(heatDetails());
    renderPage();
    expect(await screen.findByText("backend is down")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(card("p-heat/s-cool")).toBeInTheDocument());
    expect(screen.queryByText("backend is down")).toBeNull();
    expect(api.listCatalog).toHaveBeenCalledTimes(2);
  });

  test("lists every scenario as a card, two that share an id included", async () => {
    // Ids are unique per project only, so the cards are keyed by project too.
    routeApi([heatScenario(), exampleScenario()]);
    renderPage();
    await waitFor(() => expect(card("p-heat/s-cool")).toBeInTheDocument());
    const heat = within(card("p-heat/s-cool"));
    expect(heat.getByText("Cool roofs")).toBeInTheDocument();
    expect(heat.getByText("Heat study")).toBeInTheDocument();
    expect(heat.getByText("2 nodes")).toBeInTheDocument();
    expect(heat.getByText("Raise roof albedo across the district.")).toBeInTheDocument();
    expect(heat.getByText("Your dataflow")).toBeInTheDocument();
    const example = within(card("p-ex/s-cool"));
    expect(example.getByText("Baseline")).toBeInTheDocument();
    expect(example.getByText("1 node")).toBeInTheDocument();
    expect(example.getByText("Example")).toBeInTheDocument();
    expect(card("p-heat/s-cool").tagName).toBe("ARTICLE");
  });

  test("the drawer opens on the first card, as on the other catalog pages", async () => {
    routeApi([heatScenario(), exampleScenario()]);
    renderPage();
    await waitFor(() => expect(card("p-heat/s-cool")).toBeInTheDocument());
    const drawer = document.querySelector("[data-curio-browse-drawer]") as HTMLElement;
    expect(drawer).not.toBeNull();
    expect(within(drawer).getByText("Scenario info")).toBeInTheDocument();
    expect(card("p-heat/s-cool").className).toMatch(/cardActive/);
    // It reads the selected scenario's details, to mark it on the graph.
    await waitFor(() => expect(api.getScenario).toHaveBeenCalledWith("p-heat", "s-cool"));
  });

  test("the search goes to the server as q", async () => {
    routeApi([heatScenario(), exampleScenario()]);
    renderPage();
    await waitFor(() => expect(card("p-heat/s-cool")).toBeInTheDocument());
    expect(api.listCatalog).toHaveBeenCalledWith({ q: "" });
    fireEvent.change(screen.getByRole("searchbox", { name: "Search scenarios" }), {
      target: { value: "cool" },
    });
    await waitFor(() => expect(api.listCatalog).toHaveBeenCalledWith({ q: "cool" }));
    await waitFor(() =>
      expect(document.querySelector('.cardGrid [data-scenario-key="p-ex/s-cool"]')).toBeNull(),
    );
    expect(card("p-heat/s-cool")).toBeInTheDocument();
  });

  test("the By project rows narrow the grid, and toggle", async () => {
    routeApi([heatScenario(), exampleScenario()]);
    renderPage();
    await waitFor(() => expect(card("p-heat/s-cool")).toBeInTheDocument());
    // One row per project, named and counted.
    expect(railRow("project", "p-heat")).toHaveTextContent("Heat study1");
    expect(railRow("project", "p-ex")).toHaveTextContent("Chicago example1");

    fireEvent.click(railRow("project", "p-ex"));
    expect(document.querySelector('.cardGrid [data-scenario-key="p-heat/s-cool"]')).toBeNull();
    expect(card("p-ex/s-cool")).toBeInTheDocument();

    fireEvent.click(railRow("project", "p-ex"));
    expect(card("p-heat/s-cool")).toBeInTheDocument();
    expect(card("p-ex/s-cool")).toBeInTheDocument();
  });

  test("the By origin rows tell examples from the account's own", async () => {
    routeApi([heatScenario(), exampleScenario()]);
    renderPage();
    await waitFor(() => expect(card("p-heat/s-cool")).toBeInTheDocument());
    fireEvent.click(railRow("origin", "example"));
    expect(document.querySelector('.cardGrid [data-scenario-key="p-heat/s-cool"]')).toBeNull();
    expect(card("p-ex/s-cool")).toBeInTheDocument();

    fireEvent.click(railRow("project", "p-heat"));
    expect(screen.getByText("No scenarios match the current filters.")).toBeInTheDocument();
  });

  test("View details opens the modal with the scenario's three sections", async () => {
    routeApi([heatScenario()]);
    renderPage();
    await waitFor(() => expect(card("p-heat/s-cool")).toBeInTheDocument());
    fireEvent.click(within(card("p-heat/s-cool")).getByRole("button", { name: "View details" }));
    const modal = within(details() as HTMLElement);
    expect(modal.getByRole("heading", { name: "Cool roofs" })).toBeInTheDocument();
    expect(await modal.findByRole("region", { name: "Levers" })).toBeInTheDocument();
    expect(modal.getByRole("region", { name: "Fixed context" })).toBeInTheDocument();
    expect(modal.getByRole("region", { name: "Outcomes" })).toBeInTheDocument();
    // Nothing navigated: details are a modal over the page.
    expect(location).toBe("/catalog/scenarios");
  });

  test("a link with both ids opens the details, and closing leaves the plain page", async () => {
    routeApi([heatScenario(), exampleScenario()]);
    renderPage("/catalog/scenarios/p-ex/s-cool");
    expect(await screen.findByRole("heading", { name: "Scenario Catalog" })).toBeInTheDocument();
    await waitFor(() => expect(details()).not.toBeNull());
    expect(api.getScenario).toHaveBeenCalledWith("p-ex", "s-cool");
    expect(
      await within(details() as HTMLElement).findByRole("heading", { name: "Baseline" }),
    ).toBeInTheDocument();

    fireEvent.click(within(details() as HTMLElement).getByRole("button", { name: "Close" }));
    expect(details()).toBeNull();
    expect(location).toBe("/catalog/scenarios");
  });

  test("right-click offers Open source project, then View details", async () => {
    routeApi([heatScenario(), exampleScenario()]);
    renderPage();
    await waitFor(() => expect(card("p-ex/s-cool")).toBeInTheDocument());
    fireEvent.contextMenu(card("p-ex/s-cool"), { clientX: 10, clientY: 20 });
    const menu = screen.getByRole("menu", { name: "Scenario actions" });
    expect(within(menu).getAllByRole("menuitem").map((el) => el.textContent)).toEqual([
      "Open source project",
      "View details",
    ]);
    // The menu acts on the card it opened on, which the drawer now shows.
    expect(card("p-ex/s-cool").className).toMatch(/cardActive/);

    fireEvent.click(within(menu).getByRole("menuitem", { name: "Open source project" }));
    expect(await screen.findByText("canvas page")).toBeInTheDocument();
    expect(location).toBe("/dataflow/p-ex");
  });

  test("the drawer opens the source project too, and offers nothing that edits", async () => {
    routeApi([heatScenario()]);
    renderPage();
    await waitFor(() => expect(card("p-heat/s-cool")).toBeInTheDocument());
    const ctas = within(document.querySelector("[data-curio-drawer-ctas]") as HTMLElement);
    expect(ctas.getAllByRole("button").map((el) => el.textContent)).toEqual([
      "Open source project",
      "View details",
    ]);
    fireEvent.click(ctas.getByRole("button", { name: "Open source project" }));
    expect(await screen.findByText("canvas page")).toBeInTheDocument();
    expect(location).toBe("/dataflow/p-heat");
  });
});

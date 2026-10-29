/**
 * The canvas Scenario Catalog drawer: fetched only while open, read-only, its
 * cards dragged onto the canvas, and the way to a scenario's project asks
 * first when the dataflow behind it has unsaved changes. Browse all lists the
 * cards under the dataflow each comes from (from komar41's #914).
 */
import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

import { ScenarioCatalogDrawer } from "../../components/scenarios/catalog/ScenarioCatalogDrawer";
import { LEAVE_DATAFLOW } from "../../hook/useLeaveGuard";
import { scenarioCatalogApi } from "../../services/scenarioCatalog/scenarioCatalogApi";
import { exampleScenario, heatDetails, heatScenario } from "../_support/scenarioRows";

jest.mock("../../services/scenarioCatalog/scenarioCatalogApi", () => ({
  scenarioCatalogApi: { listCatalog: jest.fn(), getScenario: jest.fn() },
}));

const mockFlow = { projectDirty: false, projectId: null as string | null };
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => mockFlow,
}));

const api = scenarioCatalogApi as unknown as {
  listCatalog: jest.Mock;
  getScenario: jest.Mock;
};

let location = "";
const LocationProbe: React.FC = () => {
  location = useLocation().pathname;
  return null;
};

function renderDrawer(presented = true, onRequestClose = jest.fn()) {
  render(
    <MemoryRouter initialEntries={["/dataflow/p-current"]}>
      <Routes>
        <Route
          path="/dataflow/:id"
          element={
            <ScenarioCatalogDrawer
              presented={presented}
              onRequestClose={onRequestClose}
              onExitComplete={jest.fn()}
            />
          }
        />
      </Routes>
      <LocationProbe />
    </MemoryRouter>,
  );
  return { onRequestClose };
}

const root = () =>
  document.querySelector('[data-curio-scenario-catalog-drawer="true"]') as HTMLElement;

function card(key: string): HTMLElement {
  const el = root().querySelector(`[data-scenario-key="${key}"]`);
  if (!el) throw new Error(`no card for ${key}`);
  return el as HTMLElement;
}

/** A second scenario of Heat study. Its name sorts before the example's
 *  "Baseline", so sorted by name the two projects' cards alternate. */
const treesScenario = () =>
  heatScenario({
    key: "p-heat/s-trees",
    id: "s-trees",
    name: "Add street trees",
    description: "",
    nodeCount: 1,
  });

/** Browse all's groups, in order: each one's project, its heading (the
 *  project's name and how many scenarios it holds), and its cards' keys in
 *  order. The heading comes before the group's cards, whose titles are
 *  headings too. */
function groups() {
  return within(root())
    .getAllByRole("region")
    .map((group) => ({
      project: group.getAttribute("data-scenario-group"),
      heading: group.querySelector("h3")?.textContent,
      cards: Array.from(group.querySelectorAll("[data-scenario-key]")).map((el) =>
        el.getAttribute("data-scenario-key"),
      ),
    }));
}

const HEAT = { project: "p-heat", heading: "Heat study 2 scenarios" };
const EXAMPLE = { project: "p-ex", heading: "Chicago example 1 scenario", cards: ["p-ex/s-cool"] };

function sortBy(value: string) {
  fireEvent.change(screen.getByRole("combobox", { name: "Sort scenarios" }), {
    target: { value },
  });
}

beforeEach(() => {
  api.listCatalog.mockReset();
  api.getScenario.mockReset();
  api.listCatalog.mockResolvedValue({ items: [heatScenario(), exampleScenario()] });
  api.getScenario.mockResolvedValue(heatDetails());
  mockFlow.projectDirty = false;
  mockFlow.projectId = null;
  location = "";
});

describe("the canvas Scenario Catalog drawer", () => {
  test("a closed drawer fetches nothing and hides itself", () => {
    renderDrawer(false);
    expect(api.listCatalog).not.toHaveBeenCalled();
    expect(root()).toHaveAttribute("aria-hidden", "true");
  });

  test("an open drawer lists every scenario as a card", async () => {
    renderDrawer();
    expect(root()).toHaveAttribute("aria-hidden", "false");
    expect(screen.getByRole("dialog", { name: "Scenario Catalog" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Close Scenario Catalog drawer" })).toBeInTheDocument();
    expect(await within(root()).findByText("Cool roofs")).toBeInTheDocument();
    const heat = within(card("p-heat/s-cool"));
    expect(heat.getByText("Heat study · 2 nodes")).toBeInTheDocument();
    expect(heat.getByText("Raise roof albedo across the district.")).toBeInTheDocument();
    expect(within(card("p-ex/s-cool")).getByText("Baseline")).toBeInTheDocument();
    expect(api.listCatalog).toHaveBeenCalledWith({ q: "" });
  });

  test("a card is dragged onto the canvas as its scenario, and offers nothing that edits", async () => {
    renderDrawer();
    await within(root()).findByText("Cool roofs");
    const heat = card("p-heat/s-cool");
    expect(heat).toHaveAttribute("draggable", "true");
    expect(within(heat).queryByRole("button", { name: /delete|rename|remove/i })).toBeNull();

    const data: Record<string, string> = {};
    const dataTransfer = {
      setData: (type: string, value: string) => { data[type] = value; },
      getData: (type: string) => data[type] ?? "",
      types: [] as string[],
      effectAllowed: "",
    };
    fireEvent.dragStart(heat, { dataTransfer });
    // The canvas reads this type (MainCanvas, useScenarioDrop).
    expect(JSON.parse(data["application/x-curio-scenario"])).toEqual({
      projectId: "p-heat",
      scenarioId: "s-cool",
      name: "Cool roofs",
    });
    expect(dataTransfer.effectAllowed).toBe("copy");
    // While it is dragged the scrim lets the drag through to the canvas.
    expect(root()).toHaveAttribute("data-dragging", "true");

    fireEvent.dragEnd(heat);
    expect(root()).not.toHaveAttribute("data-dragging");
  });

  test("the search goes to the server as q", async () => {
    renderDrawer();
    await within(root()).findByText("Cool roofs");
    fireEvent.change(screen.getByPlaceholderText("Search scenarios, projects…"), {
      target: { value: "roof" },
    });
    await waitFor(() => expect(api.listCatalog).toHaveBeenCalledWith({ q: "roof" }));
  });

  test("an account with no scenario says how to make one", async () => {
    api.listCatalog.mockResolvedValue({ items: [] });
    renderDrawer();
    expect(
      await screen.findByText(
        "No scenarios yet. On a canvas, choose View > Define scenario.",
      ),
    ).toBeInTheDocument();
  });

  test("a failed load says why, and Retry loads again", async () => {
    api.listCatalog
      .mockRejectedValueOnce(new Error("backend is down"))
      .mockResolvedValue({ items: [heatScenario()] });
    renderDrawer();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("backend is down");
    fireEvent.click(within(alert).getByRole("button", { name: "Retry" }));
    expect(await within(root()).findByText("Cool roofs")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  test("View details opens the scenario's details", async () => {
    renderDrawer();
    await within(root()).findByText("Cool roofs");
    fireEvent.click(screen.getByRole("button", { name: "View Cool roofs (Heat study) details" }));
    const modal = await screen.findByRole("dialog", { name: "Scenario details" });
    expect(await within(modal).findByRole("region", { name: "Scenario nodes" })).toBeInTheDocument();
    expect(api.getScenario).toHaveBeenCalledWith("p-heat", "s-cool");
  });

  test("Open source project goes there and closes the drawer", async () => {
    const { onRequestClose } = renderDrawer();
    await within(root()).findByText("Cool roofs");
    fireEvent.click(within(card("p-heat/s-cool")).getByRole("button", { name: "Open source project" }));
    await waitFor(() => expect(location).toBe("/dataflow/p-heat"));
    expect(onRequestClose).toHaveBeenCalled();
  });

  test("with unsaved changes it asks first, and staying goes nowhere", async () => {
    mockFlow.projectDirty = true;
    const { onRequestClose } = renderDrawer();
    await within(root()).findByText("Cool roofs");
    fireEvent.click(within(card("p-heat/s-cool")).getByRole("button", { name: "Open source project" }));
    const ask = screen.getByRole("dialog", { name: LEAVE_DATAFLOW.title });
    fireEvent.click(within(ask).getByRole("button", { name: "Stay here" }));
    expect(location).toBe("/dataflow/p-current");
    expect(onRequestClose).not.toHaveBeenCalled();

    fireEvent.click(within(card("p-heat/s-cool")).getByRole("button", { name: "Open source project" }));
    fireEvent.click(screen.getByRole("button", { name: "Discard and continue" }));
    await waitFor(() => expect(location).toBe("/dataflow/p-heat"));
  });

  test("the project already open only closes the drawer", async () => {
    mockFlow.projectId = "p-heat";
    mockFlow.projectDirty = true;
    const { onRequestClose } = renderDrawer();
    await within(root()).findByText("Cool roofs");
    fireEvent.click(within(card("p-heat/s-cool")).getByRole("button", { name: "Open source project" }));
    expect(onRequestClose).toHaveBeenCalled();
    expect(screen.queryByRole("dialog", { name: LEAVE_DATAFLOW.title })).toBeNull();
    expect(location).toBe("/dataflow/p-current");
  });
});

describe("Browse all lists each dataflow's scenarios under its name", () => {
  beforeEach(() => {
    // Heat study's second scenario comes after the example's in the listing.
    api.listCatalog.mockResolvedValue({ items: [heatScenario(), exampleScenario(), treesScenario()] });
  });

  test("each group is headed by its dataflow's name and count, the newest dataflow first", async () => {
    renderDrawer();
    await within(root()).findByText("Add street trees");
    expect(groups()).toEqual([{ ...HEAT, cards: ["p-heat/s-cool", "p-heat/s-trees"] }, EXAMPLE]);
    // A group is named by its dataflow alone.
    expect(within(root()).getByRole("region", { name: "Heat study" })).toHaveAttribute(
      "data-scenario-group",
      "p-heat",
    );
  });

  test("sorted by name, a dataflow's cards stay together, its group placed by its first card", async () => {
    renderDrawer();
    await within(root()).findByText("Add street trees");
    sortBy("name");
    // By name alone the cards would alternate: Add street trees (Heat
    // study), Baseline (the example), then Cool roofs (Heat study).
    expect(groups()).toEqual([{ ...HEAT, cards: ["p-heat/s-trees", "p-heat/s-cool"] }, EXAMPLE]);
  });

  test("sorted by project, the groups follow the dataflows' names", async () => {
    renderDrawer();
    await within(root()).findByText("Add street trees");
    sortBy("project");
    expect(groups()).toEqual([EXAMPLE, { ...HEAT, cards: ["p-heat/s-trees", "p-heat/s-cool"] }]);
  });
});

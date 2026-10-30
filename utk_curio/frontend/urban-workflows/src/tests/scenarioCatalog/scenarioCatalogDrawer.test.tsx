/**
 * The canvas Scenario Catalog drawer: fetched only while open, read-only, its
 * scenarios dragged onto the canvas by their set's handle (never by a card), and the way to a scenario's project asks
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

/** A set's panel, by its name. */
function setPanel(name: string): HTMLElement {
  return within(root()).getByRole("region", { name });
}

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
      heading: `${group.querySelector("h3")?.textContent} ${group.querySelector("[data-scenario-set-count]")?.textContent}`,
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
    expect(heat.queryByText(/\d+ nodes?$/)).toBeNull();
    // Open source project is the set's, not each card's.
    expect(heat.queryByRole("button", { name: "Open source project" })).toBeNull();
    expect(heat.getByText("Raise roof albedo across the district.")).toBeInTheDocument();
    expect(within(card("p-ex/s-cool")).getByText("Baseline")).toBeInTheDocument();
    expect(api.listCatalog).toHaveBeenCalledWith({ q: "" });
  });

  test("a card is not dragged, and offers nothing that edits; its set's handle drags it", async () => {
    renderDrawer();
    await within(root()).findByText("Cool roofs");
    const heat = card("p-heat/s-cool");
    expect(heat).not.toHaveAttribute("draggable");
    expect(within(heat).queryByRole("button", { name: /delete|rename|remove/i })).toBeNull();

    // Even a scenario alone in its group is dragged by the handle.
    fireEvent.click(within(setPanel("Heat study")).getByRole("button", { name: "Pick scenarios to drag" }));
    fireEvent.click(within(heat).getByRole("checkbox", { name: "Select Cool roofs" }));
    const handle = setPanel("Heat study").querySelector("[data-scenario-drag-handle]") as HTMLElement;
    expect(handle).toHaveTextContent("Drag 1 scenario");

    const data: Record<string, string> = {};
    const dataTransfer = {
      setData: (type: string, value: string) => { data[type] = value; },
      getData: (type: string) => data[type] ?? "",
      setDragImage: jest.fn(),
      types: [] as string[],
      effectAllowed: "",
    };
    fireEvent.dragStart(handle, { dataTransfer });
    // The canvas reads this type (MainCanvas, useScenarioDrop).
    // A scenario of no set drags alone, named after its project.
    expect(JSON.parse(data["application/x-curio-scenario"])).toEqual({
      projectId: "p-heat",
      setId: "",
      setName: "Heat study",
      scenarioIds: ["s-cool"],
      names: ["Cool roofs"],
    });
    expect(dataTransfer.effectAllowed).toBe("copy");
    // While it is dragged the scrim lets the drag through to the canvas.
    expect(root()).toHaveAttribute("data-dragging", "true");

    fireEvent.dragEnd(handle);
    expect(root()).not.toHaveAttribute("data-dragging");
  });

  describe("Pick scenarios to drag: several scenarios of a set, dragged by one handle", () => {
    const PARK = { id: "park", name: "Park shade" };
    const rows = () => [
      heatScenario({ key: "p-heat/s-a", id: "s-a", name: "Existing", set: PARK }),
      heatScenario({ key: "p-heat/s-b", id: "s-b", name: "Towers", set: PARK }),
      heatScenario({ key: "p-heat/s-c", id: "s-c", name: "Cap", set: PARK }),
      exampleScenario({ set: { id: "loop", name: "Loop" } }),
      exampleScenario({ key: "p-ex/s-d", id: "s-d", name: "Removed", set: { id: "loop", name: "Loop" } }),
    ];
    const dragFrom = (el: HTMLElement) => {
      const data: Record<string, string> = {};
      const dataTransfer = {
        setData: (type: string, value: string) => { data[type] = value; },
        getData: (type: string) => data[type] ?? "",
        setDragImage: jest.fn(),
        types: [] as string[],
        effectAllowed: "",
      };
      fireEvent.dragStart(el, { dataTransfer });
      fireEvent.dragEnd(el);
      return data["application/x-curio-scenario"] ? JSON.parse(data["application/x-curio-scenario"]) : null;
    };
    const check = (name: string) => fireEvent.click(within(root()).getByRole("checkbox", { name: `Select ${name}` }));
    const handle = () => setPanel("Park shade").querySelector("[data-scenario-drag-handle]") as HTMLElement;

    beforeEach(() => api.listCatalog.mockResolvedValue({ items: rows() }));

    test("no checkboxes until Pick scenarios to drag, and a card never drags", async () => {
      renderDrawer();
      await within(root()).findByText("Towers");
      expect(within(root()).queryByRole("checkbox")).toBeNull();
      expect(card("p-heat/s-b")).not.toHaveAttribute("draggable");
      expect(dragFrom(card("p-heat/s-b"))).toBeNull();
    });

    test("in select mode the checked scenarios drag by the set's handle", async () => {
      renderDrawer();
      await within(root()).findByText("Towers");
      fireEvent.click(within(setPanel("Park shade")).getByRole("button", { name: "Pick scenarios to drag" }));
      expect(within(setPanel("Loop")).queryByRole("checkbox")).toBeNull();
      expect(handle()).toHaveAttribute("aria-disabled", "true");
      expect(handle()).toHaveTextContent("Check scenarios to drag");
      check("Existing");
      check("Cap");
      expect(handle()).toHaveTextContent("Drag 2 scenarios");
      expect(card("p-heat/s-a")).not.toHaveAttribute("draggable");
      expect(dragFrom(handle())).toEqual({
        projectId: "p-heat", setId: "park", setName: "Park shade", scenarioIds: ["s-a", "s-c"], names: ["Existing", "Cap"],
      });
    });

    test("Select all, Clear and Done; another set's Pick scenarios to drag takes over", async () => {
      renderDrawer();
      await within(root()).findByText("Towers");
      fireEvent.click(within(setPanel("Park shade")).getByRole("button", { name: "Pick scenarios to drag" }));
      fireEvent.click(within(setPanel("Park shade")).getByRole("button", { name: "Select all" }));
      expect(handle()).toHaveTextContent("Drag 3 scenarios");
      fireEvent.click(within(setPanel("Park shade")).getByRole("button", { name: "Clear" }));
      expect(handle()).toHaveTextContent("Check scenarios to drag");
      fireEvent.click(within(setPanel("Loop")).getByRole("button", { name: "Pick scenarios to drag" }));
      expect(within(setPanel("Park shade")).queryByRole("checkbox")).toBeNull();
      expect(within(setPanel("Loop")).getAllByRole("checkbox")).toHaveLength(2);
      fireEvent.click(within(setPanel("Loop")).getByRole("button", { name: "Done" }));
      expect(within(root()).queryByRole("checkbox")).toBeNull();
    });
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
    expect(await within(modal).findByRole("region", { name: "Scenario-specific nodes" })).toBeInTheDocument();
    expect(api.getScenario).toHaveBeenCalledWith("p-heat", "s-cool");
  });

  test("a card's graph marks its scenario as its details do", async () => {
    api.listCatalog.mockResolvedValue({
      items: [heatScenario({ marks: { members: ["year", "filter"], context: ["load"], outcomes: ["chart"] } })],
    });
    renderDrawer();
    await within(root()).findByText("Cool roofs");
    const svg = card("p-heat/s-cool").querySelector("svg")!;
    expect(svg).toHaveAttribute("data-thumbnail-highlight", "true");
    const roles = Array.from(svg.querySelectorAll("g[data-thumbnail-role]")).map((g) =>
      g.getAttribute("data-thumbnail-role"),
    );
    expect(roles.sort()).toEqual(["context", "member", "member", "outcome"]);
  });

  test("Open source project goes there and closes the drawer", async () => {
    const { onRequestClose } = renderDrawer();
    await within(root()).findByText("Cool roofs");
    fireEvent.click(within(setPanel("Heat study")).getByRole("button", { name: "Open source project" }));
    await waitFor(() => expect(location).toBe("/dataflow/p-heat"));
    expect(onRequestClose).toHaveBeenCalled();
  });

  test("with unsaved changes it asks first, and staying goes nowhere", async () => {
    mockFlow.projectDirty = true;
    const { onRequestClose } = renderDrawer();
    await within(root()).findByText("Cool roofs");
    fireEvent.click(within(setPanel("Heat study")).getByRole("button", { name: "Open source project" }));
    const ask = screen.getByRole("dialog", { name: LEAVE_DATAFLOW.title });
    fireEvent.click(within(ask).getByRole("button", { name: "Stay here" }));
    expect(location).toBe("/dataflow/p-current");
    expect(onRequestClose).not.toHaveBeenCalled();

    fireEvent.click(within(setPanel("Heat study")).getByRole("button", { name: "Open source project" }));
    fireEvent.click(screen.getByRole("button", { name: "Discard and continue" }));
    await waitFor(() => expect(location).toBe("/dataflow/p-heat"));
  });

  test("the project already open only closes the drawer", async () => {
    mockFlow.projectId = "p-heat";
    mockFlow.projectDirty = true;
    const { onRequestClose } = renderDrawer();
    await within(root()).findByText("Cool roofs");
    fireEvent.click(within(setPanel("Heat study")).getByRole("button", { name: "Open source project" }));
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

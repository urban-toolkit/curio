/**
 * A scenario's details: its fixed context, levers and outcomes, each node
 * with its parameter value and saved outputs, and the project graph with the
 * scenario marked on it.
 */
import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

import { ScenarioDetailModal } from "../../components/scenarios/catalog/ScenarioDetailModal";
import { LEAVE_DATAFLOW } from "../../hook/useLeaveGuard";
import { scenarioCatalogApi } from "../../services/scenarioCatalog/scenarioCatalogApi";
import { heatDetails, heatScenario } from "../_support/scenarioRows";

jest.mock("../../services/scenarioCatalog/scenarioCatalogApi", () => ({
  scenarioCatalogApi: { listCatalog: jest.fn(), getScenario: jest.fn() },
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

function renderModal(props: Partial<React.ComponentProps<typeof ScenarioDetailModal>> = {}) {
  const onClose = jest.fn();
  const onLeave = jest.fn();
  render(
    <MemoryRouter initialEntries={["/catalog/scenarios"]}>
      <Routes>
        <Route
          path="/catalog/scenarios"
          element={
            <ScenarioDetailModal
              projectId="p-heat"
              scenarioId="s-cool"
              onClose={onClose}
              onLeave={onLeave}
              {...props}
            />
          }
        />
        <Route path="/dataflow/:id" element={<div>canvas page</div>} />
      </Routes>
      <LocationProbe />
    </MemoryRouter>,
  );
  return { onClose, onLeave };
}

const modal = () => within(screen.getByRole("dialog", { name: "Scenario details" }));
const section = (name: string) => within(modal().getByRole("region", { name }));

beforeEach(() => {
  api.getScenario.mockReset();
  location = "";
});

describe("ScenarioDetailModal", () => {
  test("reads the scenario by its project and its id", async () => {
    api.getScenario.mockResolvedValue(heatDetails());
    renderModal();
    expect(await modal().findByRole("heading", { name: "Cool roofs" })).toBeInTheDocument();
    expect(api.getScenario).toHaveBeenCalledWith("p-heat", "s-cool");
    expect(modal().getByText("Raise roof albedo across the district.")).toBeInTheDocument();
    // The header names its project and its size, after the colour swatch.
    expect(modal().getByText("Heat study · 2 nodes")).toBeInTheDocument();
    expect(document.querySelector("[data-curio-scenario-swatch]")).not.toBeNull();
  });

  test("lists the fixed context, the levers and the outcomes, each by its label", async () => {
    api.getScenario.mockResolvedValue(heatDetails());
    renderModal();
    await modal().findByRole("region", { name: "Levers" });
    expect(section("Fixed context").getByText("Load parcels")).toBeInTheDocument();
    expect(section("Levers").getByText("Filter roofs")).toBeInTheDocument();
    // No title of its own, and no registry in a test: the template's name.
    expect(section("Levers").getByText("parameter")).toBeInTheDocument();
    expect(section("Outcomes").getByText("vis-vega")).toBeInTheDocument();
  });

  test("shows a Parameter node's value", async () => {
    api.getScenario.mockResolvedValue(heatDetails());
    renderModal();
    await modal().findByRole("region", { name: "Levers" });
    expect(section("Levers").getByText("year = 2020")).toBeInTheDocument();
  });

  test("shows each node's saved outputs, or says it has none", async () => {
    api.getScenario.mockResolvedValue(heatDetails());
    renderModal();
    await modal().findByRole("region", { name: "Levers" });
    expect(section("Fixed context").getByText("Parcels · geojson · 1,204 features")).toBeInTheDocument();
    expect(section("Outcomes").getByText("Roof chart data · csv · 42 rows")).toBeInTheDocument();
    // The filter saved nothing; the Parameter node's value is in the dataflow,
    // so it is not said to lack an output.
    expect(section("Levers").getAllByText("No saved output")).toHaveLength(1);
    const parameter = document.querySelector('[data-scenario-node-id="year"]') as HTMLElement;
    expect(within(parameter).queryByText("No saved output")).toBeNull();
    expect(section("Fixed context").queryByText("No saved output")).toBeNull();
  });

  test("marks the levers and the fixed context on the project graph", async () => {
    api.getScenario.mockResolvedValue(heatDetails());
    renderModal();
    await modal().findByRole("region", { name: "Levers" });
    const thumb = document.querySelector("[data-curio-scenario-thumbnail]") as HTMLElement;
    const role = (r: string) =>
      Array.from(thumb.querySelectorAll(`g[data-thumbnail-role="${r}"]`)).length;
    expect(thumb.querySelector("svg")).toHaveAttribute("data-thumbnail-highlight", "true");
    expect(role("member")).toBe(2);
    expect(role("context")).toBe(1);
    expect(role("faded")).toBe(1);
  });

  test("shows the listing's row at once, while its details load", () => {
    api.getScenario.mockReturnValue(new Promise(() => {}));
    renderModal({ fallbackScenario: heatScenario() });
    expect(modal().getByRole("heading", { name: "Cool roofs" })).toBeInTheDocument();
    expect(modal().getByText("Loading…")).toBeInTheDocument();
  });

  test("a failed read says why", async () => {
    api.getScenario.mockRejectedValue(new Error("Scenario not found"));
    renderModal();
    expect(await modal().findByRole("alert")).toHaveTextContent("Scenario not found");
  });

  test("Open source project goes to the project and closes the modal", async () => {
    api.getScenario.mockResolvedValue(heatDetails());
    const { onClose, onLeave } = renderModal();
    await modal().findByRole("heading", { name: "Cool roofs" });
    fireEvent.click(modal().getByRole("button", { name: "Open source project" }));
    expect(await screen.findByText("canvas page")).toBeInTheDocument();
    expect(location).toBe("/dataflow/p-heat");
    expect(onClose).toHaveBeenCalled();
    expect(onLeave).toHaveBeenCalled();
  });

  test("from a dataflow with unsaved changes it asks first", async () => {
    api.getScenario.mockResolvedValue(heatDetails());
    const { onClose } = renderModal({ unsavedChanges: true });
    await modal().findByRole("heading", { name: "Cool roofs" });
    fireEvent.click(modal().getByRole("button", { name: "Open source project" }));
    expect(screen.getByRole("dialog", { name: LEAVE_DATAFLOW.title })).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    expect(location).toBe("/catalog/scenarios");

    fireEvent.click(screen.getByRole("button", { name: "Discard and continue" }));
    await waitFor(() => expect(location).toBe("/dataflow/p-heat"));
  });
});

/**
 * The catalog's scenario sets: Browse all lists scenarios under their set, and
 * a set's summary is a table of its shared context and outcomes, a circle per
 * scenario, filled where that scenario uses the node.
 */
import React from "react";
import { render, screen, within } from "@testing-library/react";
import "@testing-library/jest-dom";

import { ScenarioSetSummary } from "../../components/scenarios/catalog/ScenarioSetSummary";
import { groupScenariosBySet, type ScenarioRow } from "../../services/scenarioCatalog";
import { scenarioCatalogApi } from "../../services/scenarioCatalog/scenarioCatalogApi";

jest.mock("../../services/scenarioCatalog/scenarioCatalogApi", () => ({
  scenarioCatalogApi: { getSet: jest.fn() },
}));

const project = { id: "p1", name: "Park shade", isExample: true, updatedAt: "2026-10-28" };
const row = (id: string, color: string, set?: { id: string; name: string }, p = project): ScenarioRow => ({
  key: `${p.id}/${id}`, id, name: id, color, description: "", nodeCount: 1, set, project: p, preview: null,
});

test("Browse all groups scenarios under their set, each set of its project", () => {
  const park = { id: "park", name: "Lower Manhattan park shade" };
  const other = { ...project, id: "p2", name: "Routing" };
  const groups = groupScenariosBySet([
    row("Existing", "#2a9d8f", park),
    row("Fastest", "#42a5f5", { id: "route", name: "Routing around rain and wind" }, other),
    row("Towers removed", "#e76f51", park),
    row("Old", "#111111", undefined),
  ]);
  expect(groups.map((g) => [g.set.name, g.items.map((i) => i.id)])).toEqual([
    ["Lower Manhattan park shade", ["Existing", "Towers removed"]],
    ["Routing around rain and wind", ["Fastest"]],
    ["Park shade", ["Old"]],
  ]);
});

test("a set's summary fills the circles of the scenarios that use each node", async () => {
  (scenarioCatalogApi.getSet as jest.Mock).mockResolvedValue({
    set: { id: "park", name: "Lower Manhattan park shade" },
    key: "p1/park",
    project,
    scenarios: [row("Existing", "#2a9d8f"), row("Towers removed", "#e76f51"), row("Height cap", "#6a4c93")],
    context: [{ id: "around", type: "x", label: "Buildings around parks", results: [], scenarios: ["Towers removed", "Height cap"] }],
    outcomes: [{ id: "chart", type: "x", label: "Minutes of shadow per park", results: [], scenarios: ["Existing", "Towers removed", "Height cap"] }],
  });
  render(<ScenarioSetSummary projectId="p1" setId="park" />);
  const context = within(await screen.findByRole("region", { name: "Shared context" }));
  const around = context.getByText("Buildings around parks").closest("tr")!;
  expect(within(around).getByRole("img", { name: "Existing does not use it" })).toBeInTheDocument();
  expect(within(around).getByRole("img", { name: "Towers removed uses it" })).toBeInTheDocument();
  const outcomes = within(screen.getByRole("region", { name: "Outcomes" }));
  expect(outcomes.getAllByRole("img", { name: /uses it$/ })).toHaveLength(3);
});

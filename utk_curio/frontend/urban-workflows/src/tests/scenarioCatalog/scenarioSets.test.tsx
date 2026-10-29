/**
 * The catalog's scenario sets: Browse all lists scenarios under their set, each
 * set a panel headed by its name and how many scenarios it holds.
 */
import React from "react";
import { render, screen, within } from "@testing-library/react";
import "@testing-library/jest-dom";

import { ScenarioSetGroup } from "../../components/scenarios/catalog/ScenarioSetGroup";
import { groupScenariosBySet, type ScenarioRow } from "../../services/scenarioCatalog";

const project = { id: "p1", name: "Park shade", isExample: true, updatedAt: "2026-10-28" };
const row = (id: string, color: string, set?: { id: string; name: string }, p = project): ScenarioRow => ({
  key: `${p.id}/${id}`, id, name: id, color, description: "", nodeCount: 1, set, project: p, preview: null,
});

test("Browse all groups scenarios under their set, a project's sets together", () => {
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
    ["Park shade", ["Old"]],
    ["Routing around rain and wind", ["Fastest"]],
  ]);
});

test("a set's panel is named by the set, counts its scenarios and holds their cards", () => {
  render(
    <ScenarioSetGroup name="Lower Manhattan park shade" count={2} data={{ "data-scenario-set": "park" }}>
      <article>Existing</article>
      <article>Towers removed</article>
    </ScenarioSetGroup>,
  );
  const panel = screen.getByRole("region", { name: "Lower Manhattan park shade" });
  expect(panel).toHaveAttribute("data-scenario-set", "park");
  expect(within(panel).getByText("Scenario set")).toBeInTheDocument();
  expect(within(panel).getByText("2 scenarios")).toBeInTheDocument();
  expect(within(panel).getByText("Towers removed")).toBeInTheDocument();
});

test("scenarios of no set take no Scenario set label", () => {
  render(
    <ScenarioSetGroup name="Not in a set yet" count={1} isSet={false}>
      <article>Old</article>
    </ScenarioSetGroup>,
  );
  expect(screen.getByRole("region", { name: "Not in a set yet" })).toBeInTheDocument();
  expect(screen.queryByText("Scenario set")).not.toBeInTheDocument();
  expect(screen.getByText("1 scenario")).toBeInTheDocument();
});

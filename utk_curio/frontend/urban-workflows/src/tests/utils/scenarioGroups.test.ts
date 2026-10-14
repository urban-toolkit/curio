/**
 * The Scenario Catalog drawer lists each dataflow's scenarios under its name,
 * in the order the sort gave, so two from one dataflow sit together.
 */
import { groupScenariosByProject, type ScenarioRow } from "../../services/scenarioCatalog/scenarioCatalogTypes";

const row = (id: string, project: string): ScenarioRow => ({
  key: `${project}/${id}`,
  id,
  name: id,
  color: "#3567c7",
  description: "",
  nodeCount: 1,
  project: { id: project, name: `Project ${project}`, isExample: false, updatedAt: "" },
  preview: null,
});

test("scenarios group under their dataflow, in the order each dataflow first comes", () => {
  const groups = groupScenariosByProject([row("a", "p1"), row("b", "p2"), row("c", "p1")]);
  expect(groups.map((g) => [g.project.name, g.items.map((r) => r.id)])).toEqual([
    ["Project p1", ["a", "c"]],
    ["Project p2", ["b"]],
  ]);
});

import type { GraphPreview } from "../../api/projectsApi";
import type { ScenarioDetails, ScenarioRow } from "../../services/scenarioCatalog";

/** A four-node project: a loader and a Parameter feed a filter, which feeds a
 *  chart. The scenario's levers are the Parameter and the filter. */
export const HEAT_PREVIEW: GraphPreview = {
  nodes: [
    { id: "load", type: "curio.builtin/data-loading@1", x: 0, y: 0 },
    { id: "year", type: "curio.builtin/parameter@1", x: 0, y: 200 },
    { id: "filter", type: "curio.builtin/data-transformation@1", x: 300, y: 100 },
    { id: "chart", type: "curio.builtin/vis-vega@1", x: 600, y: 100 },
  ],
  edges: [
    { source: "load", target: "filter" },
    { source: "year", target: "filter" },
    { source: "filter", target: "chart" },
  ],
};

/** A scenario in one of the account's own projects, as the listing has it. */
export function heatScenario(over: Partial<ScenarioRow> = {}): ScenarioRow {
  return {
    key: "p-heat/s-cool",
    id: "s-cool",
    name: "Cool roofs",
    color: "#3567c7",
    description: "Raise roof albedo across the district.",
    nodeCount: 2,
    project: {
      id: "p-heat",
      name: "Heat study",
      isExample: false,
      updatedAt: "2026-10-03T10:00:00Z",
    },
    preview: HEAT_PREVIEW,
    ...over,
  };
}

/** A scenario in one of Curio's examples. Its id is the same as
 *  `heatScenario`'s: an id is unique in its project only. */
export function exampleScenario(over: Partial<ScenarioRow> = {}): ScenarioRow {
  return {
    key: "p-ex/s-cool",
    id: "s-cool",
    name: "Baseline",
    color: "#2f8f4a",
    description: "",
    nodeCount: 1,
    project: {
      id: "p-ex",
      name: "Chicago example",
      isExample: true,
      updatedAt: "2026-09-01T10:00:00Z",
    },
    preview: HEAT_PREVIEW,
    ...over,
  };
}

/** `heatScenario`'s details: a loader with a saved output as its fixed
 *  context, two levers (a Parameter without a title, a titled filter) and a
 *  chart as its outcome. */
export function heatDetails(row: ScenarioRow = heatScenario()): ScenarioDetails {
  return {
    ...row,
    context: [
      {
        id: "load",
        type: "curio.builtin/data-loading@1",
        label: "Load parcels",
        results: [
          {
            datasetId: "d-parcels",
            nodeId: "load",
            title: "Parcels",
            format: "geojson",
            rowCount: null,
            featureCount: 1204,
            updatedAt: null,
          },
        ],
      },
    ],
    levers: [
      {
        id: "year",
        type: "curio.builtin/parameter@1",
        parameter: { name: "year", value: 2020 },
        results: [],
      },
      {
        id: "filter",
        type: "curio.builtin/data-transformation@1",
        label: "Filter roofs",
        results: [],
      },
    ],
    outcomes: [
      {
        id: "chart",
        type: "curio.builtin/vis-vega@1",
        results: [
          {
            datasetId: "d-chart",
            nodeId: "filter",
            title: "Roof chart data",
            format: "csv",
            rowCount: 42,
            featureCount: null,
            updatedAt: null,
          },
        ],
      },
    ],
  };
}

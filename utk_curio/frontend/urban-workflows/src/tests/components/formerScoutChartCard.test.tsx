/**
 * #1270: the charts that compare scenarios are the Vega-Lite package's nodes
 * (`curio.vega-lite@1`), no SCOUT node's. Example 06's "Mean sunlight", its
 * Bars, is tagged with its template's label on its card in a collapsed box,
 * as any package node is: the canvas reads its kind off the template its
 * shipped type names (`CanvasScenarioLayers`), registered as
 * packages/curio.vega-lite@1/manifest.json declares the package's templates,
 * never stubbed.
 */
import fs from "fs";
import path from "path";
import React from "react";
import { render, screen, within } from "@testing-library/react";
import "@testing-library/jest-dom";
import { ReactFlowProvider } from "reactflow";
import { faCircle } from "@fortawesome/free-solid-svg-icons";

jest.mock("vega", () => ({}), { virtual: true });
jest.mock("vega-lite", () => ({}), { virtual: true });

const mockFlow: Record<string, any> = {};
jest.mock("../../providers/FlowProvider", () => ({ useFlowContext: () => mockFlow }));
jest.mock("../../components/scenarios/useScenarioActions", () => ({ useScenarioActions: () => ({}) }));
jest.mock("../../components/collab/CanvasCursors", () => ({ CanvasCursors: () => null }));

import { CanvasScenarioLayers } from "../../components/scenarios/CanvasScenarioLayers";
import { registerNode } from "../../registry/nodeRegistry";
import type { NodeDescriptor } from "../../registry/types";

const ROOT = path.resolve(__dirname, "../../../../../..");
const read = (rel: string) => JSON.parse(fs.readFileSync(path.join(ROOT, rel), "utf8"));
const MANIFEST = read("packages/curio.vega-lite@1/manifest.json");
const EXAMPLE = read("docs/examples/06-back-bay-road-sunlight.json").dataflow;

beforeAll(() => {
  for (const template of MANIFEST.templates) {
    registerNode({
      id: `${MANIFEST.id}/${template.id}@1`,
      source: "package",
      package: {
        packageId: MANIFEST.id, major: 1, version: MANIFEST.version, name: MANIFEST.name, publisher: MANIFEST.publisher,
      },
      category: template.category,
      label: template.label,
      icon: faCircle,
      inputPorts: template.inputPorts ?? [],
      outputPorts: template.outputPorts ?? [],
      editor: template.editor,
      grammarId: template.grammarId,
      badge: template.badge,
      inPalette: true,
      description: "",
      hasCode: !!template.hasCode,
      hasWidgets: !!template.hasWidgets,
      hasGrammar: !!template.hasGrammar,
      adapter: { handles: [], editor: null, container: {}, useNodeBehavior: () => ({}) },
    } as unknown as NodeDescriptor);
  }
});

test("example 06's Mean sunlight, the Vega-Lite package's Bars, is tagged with its template's label on its card in a collapsed box", () => {
  const chart = EXAMPLE.nodes.find((n: any) => n.title === "Mean sunlight");
  expect(chart).toBeDefined();
  expect(chart.type).toBe("curio.vega-lite/bars");
  const template = MANIFEST.templates.find((t: any) => t.id === "bars");
  expect(template.label).toBe("Bars");
  // The node as the canvas holds it: its shipped type and its title.
  const node = {
    id: chart.id,
    type: "universal",
    position: { x: chart.x, y: chart.y },
    data: { nodeId: chart.id, nodeType: chart.type, title: chart.title },
  };
  Object.assign(mockFlow, { nodes: [node], nodeExecStatus: {}, scenarioSets: [] });
  const scenario = { id: "s-chart", name: "Shadow study", color: "#3567c7", nodes: [chart.id], collapsed: true };
  // A collapsed box holding the chart: its cards, and its parts as the box
  // lists them.
  const view: any = {
    nodes: [],
    edges: [],
    boxes: [{ scenario, x: 0, y: 0, rows: [chart.id], parts: { levers: [chart.id], context: [], outcomes: [chart.id] } }],
    frames: [],
    standIns: [],
    dots: [],
  };
  render(
    <ReactFlowProvider>
      <CanvasScenarioLayers view={view} editable />
    </ReactFlowProvider>,
  );
  const box = screen.getByTestId("scenario-box-s-chart");
  expect(box.textContent).toContain("Mean sunlight");
  expect(within(box).getByText(template.label)).toBeInTheDocument();
  expect(box.textContent).not.toMatch(/Scout|SCOUT/);
});

/**
 * #1270: Scout's charts are built-in Vega-Lite nodes. Example 06's "Mean
 * sunlight", one of them, is tagged Vega-Lite on its card in a collapsed box:
 * the canvas reads its kind off the template its shipped type names
 * (`CanvasScenarioLayers`), registered as packages/curio.builtin@1/manifest.json
 * declares the built-in templates, never stubbed.
 */
import fs from "fs";
import path from "path";
import React from "react";
import { render, screen, within } from "@testing-library/react";
import "@testing-library/jest-dom";
import { ReactFlowProvider } from "reactflow";
import { faCircle } from "@fortawesome/free-solid-svg-icons";

const mockFlow: Record<string, any> = {};
jest.mock("../../providers/FlowProvider", () => ({ useFlowContext: () => mockFlow }));
jest.mock("../../components/scenarios/useScenarioActions", () => ({ useScenarioActions: () => ({}) }));
jest.mock("../../components/collab/CanvasCursors", () => ({ CanvasCursors: () => null }));

import { CanvasScenarioLayers } from "../../components/scenarios/CanvasScenarioLayers";
import { registerNode } from "../../registry/nodeRegistry";
import type { NodeDescriptor } from "../../registry/types";

const ROOT = path.resolve(__dirname, "../../../../../..");
const read = (rel: string) => JSON.parse(fs.readFileSync(path.join(ROOT, rel), "utf8"));
const TEMPLATES: any[] = read("packages/curio.builtin@1/manifest.json").templates;
const EXAMPLE = read("docs/examples/06-back-bay-road-sunlight.json").dataflow;

beforeAll(() => {
  for (const template of TEMPLATES) {
    registerNode({
      id: `curio.builtin/${template.id}@1`,
      category: template.category,
      label: template.label,
      icon: faCircle,
      inputPorts: template.inputPorts ?? [],
      outputPorts: template.outputPorts ?? [],
      editor: template.editor,
      inPalette: true,
      description: "",
      hasCode: !!template.hasCode,
      hasWidgets: !!template.hasWidgets,
      hasGrammar: !!template.hasGrammar,
      adapter: { handles: [], editor: null, container: {}, useNodeBehavior: () => ({}) },
    } as unknown as NodeDescriptor);
  }
});

test("example 06's Mean sunlight, a chart of Scout's before, is tagged Vega-Lite on its card in a collapsed box", () => {
  const chart = EXAMPLE.nodes.find((n: any) => n.title === "Mean sunlight");
  expect(chart).toBeDefined();
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
  expect(within(box).getByText("Vega-Lite")).toBeInTheDocument();
  expect(box.textContent).not.toMatch(/Scout|Bars/);
});

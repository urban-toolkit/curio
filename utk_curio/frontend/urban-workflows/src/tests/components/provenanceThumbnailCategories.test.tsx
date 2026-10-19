/**
 * The provenance window draws each version's preview with the categories the
 * nodes' registered descriptors give now, as the Projects page draws a saved
 * project with the categories its manifests declare now. So a version saved
 * without categories is drawn in colour, and a node no registered package
 * provides keeps the category recorded with its version. Drawing changes
 * nothing that is saved.
 */
import React from "react";
import { render } from "@testing-library/react";

const rfProps: Record<string, any> = {};

jest.mock("reactflow", () => ({
  __esModule: true,
  default: (props: any) => {
    Object.assign(rfProps, props);
    return <div data-testid="inner-reactflow" />;
  },
  ReactFlowProvider: ({ children }: any) => <>{children}</>,
  Controls: () => <div />,
  Handle: () => <div />,
  BaseEdge: () => <div />,
  Position: { Top: "top", Bottom: "bottom" },
  useStore: () => undefined,
  getSmoothStepPath: () => ["M0,0"],
}));

jest.mock("../../hook/useCode", () => ({
  useCode: () => ({ loadTrill: jest.fn() }),
}));

import TrillProvenanceWindow from "../../components/menus/provenance/TrillProvenanceWindow";
import { TrillGenerator } from "../../TrillGenerator";
import { clearCategoryDescriptors, registerCategoryDescriptor } from "../_support/categoryDescriptors";

beforeAll(() => {
  registerCategoryDescriptor("acme.hydro/gauge@1", "data");
  registerCategoryDescriptor("scout.comparison/donuts@1", "vis_grammar");
});

afterAll(() => clearCategoryDescriptors());

beforeEach(() => {
  for (const k of Object.keys(rfProps)) delete rfProps[k];
  TrillGenerator.reset();
  TrillGenerator.provenanceJSON = {
    id: "wf",
    nodes: [
      {
        // Saved with no categories.
        id: "v1",
        label: "v1",
        timestamp: 1,
        preview: {
          nodes: [
            { id: "a", type: "acme.hydro/gauge@1", x: 0, y: 0 },
            { id: "b", type: "scout.comparison/donuts", x: 300, y: 0 },
          ],
          edges: [{ source: "a", target: "b" }],
        },
      },
      {
        // Recorded with categories.
        id: "v2",
        label: "v2",
        timestamp: 2,
        preview: {
          nodes: [
            { id: "a", type: "acme.hydro/gauge@1", category: "computation", x: 0, y: 0 },
            { id: "c", type: "acme.gone/gauge@1", category: "vis_simple", x: 300, y: 0 },
            { id: "d", type: "acme.gone/table@1", category: null, x: 600, y: 0 },
          ],
          edges: [],
        },
      },
    ],
    edges: [{ id: "v1_to_v2", source: "v1", target: "v2" }],
  };
});

const renderWindow = () => render(<TrillProvenanceWindow open closeModal={jest.fn()} workflowName="wf" />);

/** What each version card is handed to draw. */
const drawn = () =>
  Object.fromEntries(
    rfProps.nodes.map((n: any) => [n.id, n.data.preview.nodes.map((p: any) => [p.id, p.category])]),
  );

describe("the provenance window colours each version's nodes by category", () => {
  test("from the registered descriptors, else what the version recorded", () => {
    renderWindow();

    expect(drawn()).toEqual({
      v1: [["a", "data"], ["b", "vis_grammar"]],
      v2: [["a", "data"], ["c", "vis_simple"], ["d", null]],
    });
  });

  test("a version card paints the bars in those colours", () => {
    renderWindow();
    const Card = rfProps.nodeTypes.trillNode;
    const v1 = rfProps.nodes.find((n: any) => n.id === "v1");

    const { container } = render(<Card {...({ id: "v1", data: v1.data } as any)} />);

    const fills = Array.from(container.querySelectorAll("g")).map((g) => g.querySelectorAll("rect")[1].getAttribute("fill"));
    expect(fills).toEqual(["var(--curio-category-data-fg)", "var(--curio-category-vis-fg)"]);
  });

  test("drawing leaves the saved versions as they were", () => {
    renderWindow();

    const saved = TrillGenerator.getSerializableDataflowProvenance().graph.nodes;
    expect(saved[0].preview.nodes[0]).toEqual({ id: "a", type: "acme.hydro/gauge@1", x: 0, y: 0 });
    expect(saved[1].preview.nodes[0].category).toBe("computation");
  });
});

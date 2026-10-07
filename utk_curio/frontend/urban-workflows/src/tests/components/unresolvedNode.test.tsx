/**
 * The node a canvas renders when nothing provides its type (#233).
 *
 * Reported as "Street-level computer vision nodes remain stuck on 'Loading
 * node…'", with a second symptom that turned out to be the same defect:
 * "connections involving these nodes also fail to render". Both are covered
 * here, because the placeholder is the cause of each - it said the wrong thing,
 * and it rendered no handles for React Flow to attach edges to.
 *
 * In the notebook view the placeholder is a cell like any other: the page's
 * cell width, and its dots on its right edge where every cell has them, so its
 * connections run in the bar.
 */
import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const mockOpenDrawer = jest.fn();
jest.mock("../../providers/packages/NodeCatalogDrawerProvider", () => ({
  useNodeCatalogDrawer: () => ({
    openNodeCatalogDrawer: mockOpenDrawer,
    closeNodeCatalogDrawer: jest.fn(),
    isNodeCatalogDrawerOpen: false,
  }),
}));

let mockEdges: any[] = [];
let mockNodes: any[] = [];
jest.mock("reactflow", () => ({
  __esModule: true,
  useEdges: () => mockEdges,
  useNodes: () => mockNodes,
  Position: { Left: "left", Right: "right", Top: "top", Bottom: "bottom" },
  // Render a stand-in carrying the same data attributes the real Handle puts
  // in the DOM, which is all React Flow measures ports from, with the side and
  // the place it is given.
  Handle: ({ id, type, position, style, title, children }: any) => (
    <div
      className="react-flow__handle"
      data-handleid={id}
      data-handletype={type}
      data-position={position}
      data-top={style?.top === undefined ? "" : String(style.top)}
      data-bottom={style?.bottom === undefined ? "" : String(style.bottom)}
      title={title}
    >
      {children}
    </div>
  ),
}));

import {
  UnresolvedNode,
  packageDisplayName,
  packageIdFromNodeType,
} from "../../components/UnresolvedNode";
import { NotebookViewContext } from "../../providers/flow/notebookViewContext";
import { notebookCellMinHeight, notebookHandlePlaces } from "../../utils/notebookLayout";

const STREETVISION = "curio.streetvision/image-segmentation";

beforeEach(() => {
  mockEdges = [];
  mockNodes = [];
  mockOpenDrawer.mockClear();
});

const handleIds = (container: HTMLElement, type: "source" | "target") =>
  Array.from(container.querySelectorAll(`[data-handletype="${type}"]`)).map((el) =>
    el.getAttribute("data-handleid"),
  );

describe("packageIdFromNodeType", () => {
  it("reads the package coordinate out of a canonical type", () => {
    // No lockfile needed: the package id is right there in the node type,
    // which is what lets the card name it even when nothing resolved.
    expect(packageIdFromNodeType(STREETVISION)).toBe("curio.streetvision");
    expect(packageIdFromNodeType("curio.builtin/vis-vega@1")).toBe("curio.builtin");
  });

  it("returns null for anything it cannot read", () => {
    // A legacy plain-string type has no package to offer, so the card must not
    // invent one.
    expect(packageIdFromNodeType("DATA_LOADING")).toBeNull();
    expect(packageIdFromNodeType("nopackage/thing")).toBeNull();
    expect(packageIdFromNodeType(undefined)).toBeNull();
  });
});

describe("packageDisplayName", () => {
  it("turns a package id into something readable", () => {
    expect(packageDisplayName("curio.streetvision")).toBe("Streetvision");
    expect(packageDisplayName("ai.utk.uhvi")).toBe("Uhvi");
    expect(packageDisplayName("curio.example-ui")).toBe("Example Ui");
  });
});

describe("UnresolvedNode", () => {
  it("keeps saying 'Loading' while the registry might still deliver", () => {
    // The wait is correct here: a node from a saved dataflow routinely mounts
    // before its package's descriptor has registered.
    render(
      <UnresolvedNode nodeId="n1" nodeType={STREETVISION} registryReady={false} />,
    );
    expect(screen.getByText("Loading node…")).toBeInTheDocument();
    expect(screen.queryByTestId("unresolved-node")).toBeNull();
  });

  it("says the package is missing once the registry has settled", () => {
    // This is the bug: after the registry settles the wait is over, and
    // "Loading node…" becomes a permanent lie with no way to see past it.
    render(
      <UnresolvedNode nodeId="n1" nodeType={STREETVISION} registryReady />,
    );
    expect(screen.queryByText("Loading node…")).toBeNull();
    expect(screen.getByText("Missing node package")).toBeInTheDocument();
    expect(screen.getByText("Streetvision")).toBeInTheDocument();
  });

  it("says so when the type names no package to blame (#349)", () => {
    // This used to keep saying "Loading node…" for ever. The registry has
    // settled and a legacy plain-string type names no package, so waiting can
    // never resolve it - the same dead end #233 fixed for installable
    // packages, on a node-type shape that fix did not recognise.
    render(<UnresolvedNode nodeId="n1" nodeType="DATA_LOADING" registryReady />);
    expect(screen.queryByText("Loading node…")).toBeNull();
    expect(screen.getByText("Unrecognized node type")).toBeInTheDocument();
    expect(screen.getByText("DATA_LOADING")).toBeInTheDocument();
  });

  it("offers no install button for a type nothing can provide", () => {
    // Amber + Install means "one click fixes this". Here the type itself is
    // the problem, so an install button would send the user looking for a
    // package that does not exist.
    render(<UnresolvedNode nodeId="n1" nodeType="DATA_LOADING" registryReady />);
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByText("Missing node package")).toBeNull();
  });

  it.each([
    ["an empty type", ""],
    ["a type with no package prefix", "computation-analysis"],
    ["a prefix that is not a dotted package id", "curio/thing"],
    ["a leading slash", "/thing"],
  ])("is terminal for %s", (_label, nodeType) => {
    // Every way packageIdFromNodeType returns null, since they are all equally
    // unresolvable once the registry is ready.
    render(<UnresolvedNode nodeId="n1" nodeType={nodeType} registryReady />);
    expect(screen.queryByText("Loading node…")).toBeNull();
    expect(screen.getByText("Unrecognized node type")).toBeInTheDocument();
  });

  it("keeps waiting on an unknown type while the registry is still loading", () => {
    // The state the old guard conflated with the one above: not ready yet, so
    // the registry may still deliver. Waiting is right here.
    render(<UnresolvedNode nodeId="n1" nodeType="DATA_LOADING" registryReady={false} />);
    expect(screen.getByText("Loading node…")).toBeInTheDocument();
    expect(screen.queryByText("Unrecognized node type")).toBeNull();
  });

  it("renders handles on the unrecognized-type card too", () => {
    // React Flow reads port bounds from `.react-flow__handle` children; a card
    // without them drops every incident edge with error008. Every branch of
    // this component has to carry them - that is the #233 half people forget.
    mockEdges = [
      { id: "e1", source: "up", target: "n1", targetHandle: "in" },
      { id: "e2", source: "n1", target: "join", sourceHandle: "out" },
    ];
    const { container } = render(
      <UnresolvedNode nodeId="n1" nodeType="DATA_LOADING" registryReady />,
    );
    expect(handleIds(container, "target")).toEqual(["in"]);
    expect(handleIds(container, "source")).toEqual(["out"]);
  });

  it("opens the catalog drawer on the package it needs", () => {
    // Install stays the user's click - a package can pull large dependencies,
    // so this hands them the decision rather than making it.
    render(
      <UnresolvedNode nodeId="n1" nodeType={STREETVISION} registryReady />,
    );
    return userEvent.click(screen.getByRole("button")).then(() => {
      expect(mockOpenDrawer).toHaveBeenCalledWith({
        search: "curio.streetvision",
      });
    });
  });

  it("renders a handle for every port its edges reference", () => {
    // The missing-connections half of #233. React Flow reads port bounds from
    // `.react-flow__handle` children; with none, EdgeRenderer logs error008
    // and returns null for the edge. The edges were in state all along.
    mockEdges = [
      { id: "e1", source: "up", target: "n1", targetHandle: "in" },
      { id: "e2", source: "n1", target: "join", sourceHandle: "out" },
      { id: "e3", source: "n1", target: "sj", sourceHandle: "out_points" },
    ];
    const { container } = render(
      <UnresolvedNode nodeId="n1" nodeType={STREETVISION} registryReady />,
    );
    expect(handleIds(container, "target")).toEqual(["in"]);
    expect(handleIds(container, "source").sort()).toEqual(["out", "out_points"]);
  });

  it("renders handles while still loading, too", () => {
    // Otherwise every edge would vanish for the duration of the load and pop
    // back, which is its own kind of wrong.
    mockEdges = [{ id: "e1", source: "up", target: "n1", targetHandle: "in" }];
    const { container } = render(
      <UnresolvedNode nodeId="n1" nodeType={STREETVISION} registryReady={false} />,
    );
    expect(container.querySelectorAll(".react-flow__handle").length).toBeGreaterThan(0);
  });

  it("offers a default port pair when nothing is connected", () => {
    const { container } = render(
      <UnresolvedNode nodeId="n1" nodeType={STREETVISION} registryReady />,
    );
    expect(handleIds(container, "target")).toEqual(["in"]);
    expect(handleIds(container, "source")).toEqual(["out"]);
  });

  it("falls back to the default handle id when an edge carries none", () => {
    // `loadTrill` writes edges whose handle ids can be absent; the reader
    // infers them elsewhere, so the placeholder must not drop the edge.
    mockEdges = [{ id: "e1", source: "up", target: "n1" }];
    const { container } = render(
      <UnresolvedNode nodeId="n1" nodeType={STREETVISION} registryReady />,
    );
    expect(handleIds(container, "target")).toEqual(["in"]);
  });

  it("keeps its inputs on its left edge and its outputs on its right on the canvas", () => {
    mockEdges = [
      { id: "e1", source: "up", target: "n1", targetHandle: "in" },
      { id: "e2", source: "n1", target: "join", sourceHandle: "out" },
    ];
    const { container } = render(
      <UnresolvedNode nodeId="n1" nodeType={STREETVISION} registryReady />,
    );
    expect(container.querySelector('[data-handleid="in"]')).toHaveAttribute("data-position", "left");
    expect(container.querySelector('[data-handleid="out"]')).toHaveAttribute("data-position", "right");
    expect((container.firstElementChild as HTMLElement).style.width).toBe("");
  });
});

/** The page's cell width the view hands its cells. */
const CELL_WIDTH = 1065;

function renderInNotebook(ui: React.ReactElement) {
  return render(
    <NotebookViewContext.Provider value={{ on: true, laneX: new Map(), cellWidth: CELL_WIDTH, reveal: () => true }}>
      {ui}
    </NotebookViewContext.Provider>,
  );
}

describe("UnresolvedNode in the notebook view", () => {
  // Fed by a package node, feeding another node: one input dot, one output dot.
  const handles = [
    { id: "in", type: "target" as const },
    { id: "out", type: "source" as const },
  ];

  beforeEach(() => {
    mockEdges = [
      { id: "e1", source: "load", target: "n1", targetHandle: "in" },
      { id: "e2", source: "n1", target: "join", sourceHandle: "out" },
    ];
    // A package node's own label: how resolveNodeDisplayLabel names a node
    // without consulting the registry (a numeric type id).
    mockNodes = [{ id: "load", data: { nodeId: "load", nodeType: "1024", packageTemplateLabel: "Load roads" } }];
  });

  it.each([
    ["missing its package", STREETVISION, true],
    ["of an unrecognized type", "DATA_LOADING", true],
    ["still loading", STREETVISION, false],
  ])("is a cell like any other when %s: the page's width, its dots on its right edge where every cell's are", (
    _label, nodeType, registryReady,
  ) => {
    const { container } = renderInNotebook(
      <UnresolvedNode nodeId="n1" nodeType={nodeType as string} registryReady={registryReady as boolean} />,
    );
    const places = notebookHandlePlaces(handles);
    for (const { id } of handles) {
      const dot = container.querySelector(`[data-handleid="${id}"]`);
      const place = places.get(id) as { top: number | string; bottom?: number };
      expect(dot).toHaveAttribute("data-position", "right");
      expect(dot).toHaveAttribute("data-top", String(place.top));
      expect(dot).toHaveAttribute("data-bottom", place.bottom === undefined ? "" : String(place.bottom));
    }
    const card = container.firstElementChild as HTMLElement;
    expect(card.style.width).toBe(`${CELL_WIDTH}px`);
    expect(card.style.minHeight).toBe(`${notebookCellMinHeight(handles)}px`);
  });

  it("numbers its input dot and names what feeds it, as every cell's dots do", () => {
    const { container } = renderInNotebook(
      <UnresolvedNode nodeId="n1" nodeType={STREETVISION} registryReady />,
    );
    expect(container.querySelector('[data-handleid="in"]')).toHaveTextContent("0");
    expect(container.querySelector('[data-handleid="in"]')).toHaveAttribute("title", "input 0 · Load roads");
    expect(container.querySelector('[data-handleid="out"]')).toHaveAttribute("title", "output");
  });
});

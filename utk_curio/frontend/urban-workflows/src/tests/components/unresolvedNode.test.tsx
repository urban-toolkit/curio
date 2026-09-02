/**
 * The node a canvas renders when nothing provides its type (#233).
 *
 * Reported as "Street-level computer vision nodes remain stuck on 'Loading
 * node…'", with a second symptom that turned out to be the same defect:
 * "connections involving these nodes also fail to render". Both are covered
 * here, because the placeholder is the cause of each - it said the wrong thing,
 * and it rendered no handles for React Flow to attach edges to.
 */
import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const mockOpenDrawer = jest.fn();
jest.mock("../../providers/NodeCatalogDrawerProvider", () => ({
  useNodeCatalogDrawer: () => ({
    openNodeCatalogDrawer: mockOpenDrawer,
    closeNodeCatalogDrawer: jest.fn(),
    isNodeCatalogDrawerOpen: false,
  }),
}));

let mockEdges: any[] = [];
jest.mock("reactflow", () => ({
  __esModule: true,
  useEdges: () => mockEdges,
  Position: { Left: "left", Right: "right" },
  // Render a stand-in carrying the same data attributes the real Handle puts
  // in the DOM, which is all React Flow measures ports from.
  Handle: ({ id, type }: { id: string; type: string }) => (
    <div className="react-flow__handle" data-handleid={id} data-handletype={type} />
  ),
}));

import {
  UnresolvedNode,
  packageDisplayName,
  packageIdFromNodeType,
} from "../../components/UnresolvedNode";

const STREETVISION = "curio.streetvision/street-view-fetcher";

beforeEach(() => {
  mockEdges = [];
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
    expect(packageDisplayName("ai.urbanlab.uhvi")).toBe("Uhvi");
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

  it("keeps waiting when the type names no package to blame", () => {
    render(<UnresolvedNode nodeId="n1" nodeType="DATA_LOADING" registryReady />);
    expect(screen.getByText("Loading node…")).toBeInTheDocument();
  });

  it("opens the catalog drawer on the package it needs", () => {
    // Install stays the user's click - Street Vision pulls ~3 GB of torch, so
    // this hands them the decision rather than making it.
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
});

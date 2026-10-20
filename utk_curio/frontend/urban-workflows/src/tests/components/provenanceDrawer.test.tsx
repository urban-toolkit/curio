/**
 * View > Provenance opens the dataflow's versions in a drawer on the right,
 * with the catalog drawers' pin and width, listed as Curio's Nest lists work.
 * A click opens a version and shows it; only its own button puts it on the
 * canvas.
 */
import React from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

const mockLoadTrill = jest.fn();
jest.mock("../../hook/useCode", () => ({
  useCode: () => ({ loadTrill: mockLoadTrill }),
}));
let mockNodes: { id: string }[] = [{ id: "n1" }];
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ workflowNameRef: { current: "Heat study" }, nodes: mockNodes }),
}));

import { ProvenanceDrawerProvider, useProvenanceDrawerOptional } from "../../providers/ProvenanceDrawerProvider";
import ProvenanceProvider, { type NodeExecRecord, useProvenanceContext } from "../../providers/ProvenanceProvider";
import { TrillGenerator } from "../../TrillGenerator";

const mockRestore = jest.fn();

function Opener() {
  const drawer = useProvenanceDrawerOptional()!;
  return (
    <>
      <button type="button" onClick={drawer.openDataflowProvenance}>
        View provenance
      </button>
      <button
        type="button"
        onClick={() => drawer.openNodeProvenance({ nodeId: "n1", title: "Heat index", restore: mockRestore })}
      >
        Node provenance pill
      </button>
    </>
  );
}

const root = () => document.querySelector('[data-curio-provenance-drawer="true"]');
const item = (id: string) => document.querySelector<HTMLElement>(`[data-provenance-item="${id}"]`);
const head = (id: string) => item(id)!.querySelector("button")!;
const shownIds = () =>
  Array.from(document.querySelectorAll<HTMLElement>("[data-provenance-item]")).map((el) => el.dataset.provenanceItem);

const version = (id: string, nodes: string[]) => ({
  id,
  label: id,
  timestamp: 1_700_000_000_000 + Number(id.slice(1)) * 60_000,
  preview: { nodes: nodes.map((n, i) => ({ id: n, type: "acme.none/x@1", x: i * 300, y: 0 })), edges: [] },
});

beforeEach(() => {
  mockLoadTrill.mockReset();
  TrillGenerator.reset();
  // v3 was tried from v2; then the work went back to v2 and on to v4 and v5.
  TrillGenerator.provenanceJSON = {
    id: "wf",
    nodes: [
      version("v1", []),
      version("v2", ["a"]),
      version("v3", ["a", "b"]),
      version("v4", ["a", "c"]),
      version("v5", ["a", "c", "d"]),
    ],
    edges: [
      { id: "v1_to_v2", source: "v1", target: "v2", label: "Node added" },
      { id: "v2_to_v3", source: "v2", target: "v3", label: "Node added" },
      { id: "v2_to_v4", source: "v2", target: "v4", label: "Node added" },
      { id: "v4_to_v5", source: "v4", target: "v5", label: "Node added" },
    ],
  };
  for (const id of ["v1", "v2", "v3", "v4", "v5"]) {
    TrillGenerator.list_of_trills[id] = { dataflow: { name: "Heat study", nodes: [], edges: [] } };
  }
  TrillGenerator.latestTrill = "v5";
});

async function openDrawer() {
  const utils = render(
    <ProvenanceDrawerProvider>
      <Opener />
    </ProvenanceDrawerProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "View provenance" }));
  await waitFor(() => expect(root()).toHaveAttribute("aria-hidden", "false"));
  return utils;
}

describe("the provenance drawer", () => {
  test("opens on the right like the catalog drawers: their width, their pin, a title and the dataflow's name", async () => {
    await openDrawer();
    const dialog = screen.getByRole("dialog", { name: "Dataflow provenance" });
    expect(dialog.className).toContain("drawer");
    expect(dialog.className).not.toContain("drawerWide");
    expect(within(dialog).getByRole("heading", { name: "Dataflow provenance", level: 2 })).toBeInTheDocument();
    expect(within(dialog).getByText("Versions of Heat study")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Pin drawer open" })).toBeInTheDocument();
  });

  test("lists the line to the newest version, with the version left behind folded under the one it left from", async () => {
    await openDrawer();
    expect(shownIds()).toEqual(["v1", "v2", "v4", "v5"]);
    expect(item("v5")).toHaveAttribute("data-provenance-current", "true");
    expect(item("v2")).not.toHaveAttribute("data-provenance-current");

    const fold = within(item("v2")!.closest("li")!).getByRole("button", { name: /1 version on another branch/ });
    expect(fold).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(fold);
    expect(fold).toHaveAttribute("aria-expanded", "true");
    expect(shownIds()).toEqual(["v1", "v2", "v3", "v4", "v5"]);
  });

  test("a click opens a version and puts nothing back", async () => {
    await openDrawer();
    fireEvent.click(head("v2"));

    expect(head("v2")).toHaveAttribute("aria-expanded", "true");
    expect(within(item("v2")!).getByText("1 node, 0 connections")).toBeInTheDocument();
    expect(within(item("v2")!).getByRole("button", { name: "Put this version on the canvas" })).toBeInTheDocument();
    expect(mockLoadTrill).not.toHaveBeenCalled();
    expect(TrillGenerator.latestTrill).toBe("v5");
  });

  test("the version in use says so instead of offering itself", async () => {
    await openDrawer();
    fireEvent.click(head("v5"));
    expect(within(item("v5")!).getByText("On the canvas now")).toBeInTheDocument();
    expect(within(item("v5")!).queryByRole("button", { name: "Put this version on the canvas" })).toBeNull();
  });

  test("its button puts the version on the canvas, keeping the history, and the dot moves to it", async () => {
    await openDrawer();
    fireEvent.click(head("v2"));
    fireEvent.click(within(item("v2")!).getByRole("button", { name: "Put this version on the canvas" }));

    expect(mockLoadTrill).toHaveBeenCalledTimes(1);
    expect(mockLoadTrill).toHaveBeenCalledWith(TrillGenerator.list_of_trills.v2, undefined, true);
    expect(TrillGenerator.latestTrill).toBe("v2");
    expect(item("v2")).toHaveAttribute("data-provenance-current", "true");
    expect(item("v5")).not.toHaveAttribute("data-provenance-current");
    expect(within(item("v2")!).getByText("On the canvas now")).toBeInTheDocument();
    expect(shownIds()).toEqual(["v1", "v2", "v4", "v5"]);
  });

  test("pinned, the scrim and Escape leave it open, and its close button closes it", async () => {
    await openDrawer();
    fireEvent.click(screen.getByRole("button", { name: "Pin drawer open" }));
    expect(screen.getByRole("button", { name: "Unpin drawer" })).toHaveAttribute("aria-pressed", "true");

    fireEvent.keyDown(window, { key: "Escape" });
    fireEvent.click(screen.getByRole("button", { name: "Dismiss Dataflow provenance" }));
    expect(root()).toHaveAttribute("aria-hidden", "false");

    fireEvent.click(screen.getByRole("button", { name: "Close Dataflow provenance" }));
    await waitFor(() => expect(root()).toBeNull());
  });

  test("unpinned, Escape closes it", async () => {
    await openDrawer();
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(root()).toBeNull());
  });

  test("says so while the dataflow has no version", async () => {
    TrillGenerator.reset();
    await openDrawer();
    expect(screen.getByText("No versions yet")).toBeInTheDocument();
  });
});

describe("a node's runs in the drawer, from its Provenance pill", () => {
  // Run 1, then run 2 from it; back to run 1, then run 3 from it.
  const run = (id: number, parentId: number | null, code: string): NodeExecRecord => ({
    id,
    parentId,
    code,
    inputs: ["DATAFRAME"],
    outputs: ["DATAFRAME"],
    startTime: `Oct 20 2026 06:00:0${id}`,
    endTime: `Oct 20 2026 06:00:0${id + 2}`,
  });
  const seen: { provenance?: ReturnType<typeof useProvenanceContext> } = {};
  function Probe() {
    seen.provenance = useProvenanceContext();
    return null;
  }
  const tree = () => (
    <ProvenanceProvider>
      <Probe />
      <ProvenanceDrawerProvider>
        <Opener />
      </ProvenanceDrawerProvider>
    </ProvenanceProvider>
  );
  const fold = () => within(item("1")!.closest("li")!).getByRole("button", { name: /1 run on another branch/ });

  beforeEach(() => {
    mockRestore.mockReset();
    mockNodes = [{ id: "n1" }];
  });

  async function openRuns() {
    const utils = render(tree());
    act(() => {
      seen.provenance!.loadNodeProvenance({
        n1: [run(1, null, "df = load()"), run(2, 1, "df = load()\ndf = df.head()"), run(3, 1, "df = load()\ndf = df.tail()")],
      });
      seen.provenance!.setSelectedExec("n1", 3);
    });
    fireEvent.click(screen.getByRole("button", { name: "Node provenance pill" }));
    await waitFor(() => expect(root()).toHaveAttribute("aria-hidden", "false"));
    return utils;
  }

  test("opens with the node's name and its runs, the line to the newest, the run left behind folded", async () => {
    await openRuns();
    const dialog = screen.getByRole("dialog", { name: "Node provenance" });
    expect(within(dialog).getByText("Runs of Heat index")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Pin drawer open" })).toBeInTheDocument();
    expect(shownIds()).toEqual(["1", "3"]);
    expect(item("3")).toHaveAttribute("data-provenance-current", "true");
    expect(fold()).toHaveAttribute("aria-expanded", "false");
    expect(item("1")!.textContent).toMatch(/In: DATAFRAME \| Out: DATAFRAME/);
  });

  test("a click opens a run: what it read and returned, when and how long it ran, its code; nothing is put back", async () => {
    await openRuns();
    fireEvent.click(head("3"));

    expect(item("3")!.querySelector("pre")!.textContent).toBe("df = load()\ndf = df.tail()");
    expect(within(item("3")!).getByText(/^Started .+, ran for 2 s$/)).toBeInTheDocument();
    expect(within(item("3")!).getByText("The next run branches from this one")).toBeInTheDocument();
    expect(within(item("3")!).getByRole("button", { name: "Put this code back in the node" })).toBeInTheDocument();
    expect(mockRestore).not.toHaveBeenCalled();
  });

  test("its button puts the code back in the node, and the next run branches from it", async () => {
    await openRuns();
    fireEvent.click(fold());
    fireEvent.click(head("2"));
    fireEvent.click(within(item("2")!).getByRole("button", { name: "Put this code back in the node" }));

    expect(mockRestore).toHaveBeenCalledTimes(1);
    expect(mockRestore).toHaveBeenCalledWith("df = load()\ndf = df.head()");
    expect(seen.provenance!.selectedParentExecRef.current.n1).toBe(2);
    expect(item("2")).toHaveAttribute("data-provenance-current", "true");
    expect(item("3")).not.toHaveAttribute("data-provenance-current");
  });

  test("a run filed while the drawer is open joins the list as the one in use", async () => {
    await openRuns();
    act(() => {
      seen.provenance!.nodeExecProv(
        "Oct 20 2026 06:01:00", "Oct 20 2026 06:01:01", "wf", "n1", ["DATAFRAME"], ["ERROR"], "df = broken()",
      );
    });
    expect(shownIds()).toEqual(["1", "3", "4"]);
    expect(item("4")).toHaveAttribute("data-provenance-current", "true");
    expect(item("4")!.textContent).toMatch(/In: DATAFRAME \| Out: ERROR/);
  });

  test("opened, the fold lists the run left behind under the run it left from, on a line of its own", async () => {
    await openRuns();
    fireEvent.click(fold());
    expect(fold()).toHaveAttribute("aria-expanded", "true");
    expect(shownIds()).toEqual(["1", "2", "3"]);
    expect(item("2")!.closest("ol")).toHaveAttribute("data-provenance-line", "1");
    expect(item("3")!.closest("ol")).toHaveAttribute("data-provenance-line", "0");
  });

  test("says so while the node has no run", async () => {
    render(tree());
    fireEvent.click(screen.getByRole("button", { name: "Node provenance pill" }));
    await waitFor(() => expect(root()).toHaveAttribute("aria-hidden", "false"));
    expect(screen.getByText("No runs yet")).toBeInTheDocument();
  });

  test("closes when its node leaves the canvas", async () => {
    const { rerender } = await openRuns();
    mockNodes = [];
    rerender(tree());
    await waitFor(() => expect(root()).toBeNull());
  });
});

describe("the drawer opens on the version in use", () => {
  // jsdom lays nothing out: give the drawer's body a scrolling box, and the
  // version in use a place far down it.
  const realStyle = window.getComputedStyle.bind(window);
  const isBody = (el: Element) => el.classList?.contains("scrollBody");

  beforeEach(() => {
    jest.spyOn(window, "getComputedStyle").mockImplementation((el: Element, pseudo?: string | null) => {
      const style = realStyle(el, pseudo);
      if (!isBody(el)) return style;
      return new Proxy(style, {
        get: (target, prop) => {
          if (prop === "overflowY") return "auto";
          const value = Reflect.get(target, prop, target);
          return typeof value === "function" ? value.bind(target) : value;
        },
      });
    });
    Object.defineProperty(HTMLElement.prototype, "scrollHeight", {
      configurable: true,
      get() {
        return isBody(this) ? 2000 : 0;
      },
    });
    Object.defineProperty(HTMLElement.prototype, "clientHeight", {
      configurable: true,
      get() {
        return isBody(this) ? 400 : 0;
      },
    });
    jest.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
      const top = this.getAttribute("data-provenance-current") === "true" ? 1500 : 0;
      return { top, bottom: top, left: 0, right: 0, width: 0, height: 0, x: 0, y: top, toJSON: () => ({}) } as DOMRect;
    });
  });

  afterEach(() => {
    jest.restoreAllMocks();
    delete (HTMLElement.prototype as { scrollHeight?: number }).scrollHeight;
    delete (HTMLElement.prototype as { clientHeight?: number }).clientHeight;
  });

  test("scrolled to the middle of its body, each time it opens", async () => {
    const body = () => root()!.querySelector<HTMLElement>(".scrollBody")!;
    await openDrawer();
    expect(body().scrollTop).toBe(1300);

    fireEvent.click(screen.getByRole("button", { name: "Close Dataflow provenance" }));
    await waitFor(() => expect(root()).toBeNull());
    fireEvent.click(screen.getByRole("button", { name: "View provenance" }));
    await waitFor(() => expect(root()).toHaveAttribute("aria-hidden", "false"));
    await waitFor(() => expect(body().scrollTop).toBe(1300));
  });
});

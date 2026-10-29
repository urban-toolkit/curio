/**
 * View > Provenance opens the dataflow's versions in a drawer on the right,
 * with the catalog drawers' pin and width, listed as Curio's Nest lists work.
 * A click opens a version and shows it; only its own button puts it on the
 * canvas. On a canvas bound to the dataflow's doc, the versions and a node's
 * entries are the server's.
 */
import React from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

const mockLoadTrill = jest.fn();
jest.mock("../../hook/useCode", () => ({
  useCode: () => ({ loadTrill: mockLoadTrill }),
}));
let mockNodes: { id: string; data?: unknown }[] = [{ id: "n1" }];
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ workflowNameRef: { current: "Heat study" }, nodes: mockNodes }),
}));
jest.mock("../../api/historyApi", () => ({
  historyApi: {
    versions: jest.fn(),
    entries: jest.fn(),
    putBack: jest.fn(),
    clearBefore: jest.fn(),
    writeCode: jest.fn(),
  },
}));
const mockShowToast = jest.fn();
jest.mock("../../providers/ToastProvider", () => ({
  ...jest.requireActual("../../providers/ToastProvider"),
  useOptionalToastContext: () => ({ showToast: mockShowToast }),
}));
const mockRemote = new Map<string, (payload: unknown) => void>();
jest.mock("../../providers/CollaborationProvider", () => ({
  ...jest.requireActual("../../providers/CollaborationProvider"),
  useCollab: () => ({
    connected: false,
    participantId: null,
    role: null,
    users: [],
    lockedNodes: {},
    activity: [],
    lockNode: () => undefined,
    unlockNode: () => undefined,
    resolveConflict: () => undefined,
    broadcastOutputProduced: () => undefined,
    signalExecDisplay: () => undefined,
    onRemote: (event: string, handler: (payload: unknown) => void) => {
      mockRemote.set(event, handler);
      return () => {
        mockRemote.delete(event);
      };
    },
  }),
}));

import { ProvenanceDrawerProvider, useProvenanceDrawerOptional } from "../../providers/ProvenanceDrawerProvider";
import ProvenanceProvider, { type NodeExecRecord, useProvenanceContext } from "../../providers/ProvenanceProvider";
import { TrillGenerator } from "../../TrillGenerator";
import { historyApi, type ServerVersions } from "../../api/historyApi";
import { HISTORY_CHANGED_EVENT, setServerHistory, type ServerHistory } from "../../providers/history/serverHistory";

const mockRestore = jest.fn();
const mockShowCode = jest.fn();

function Opener() {
  const drawer = useProvenanceDrawerOptional()!;
  return (
    <>
      <button type="button" onClick={drawer.openDataflowProvenance}>
        View provenance
      </button>
      <button
        type="button"
        onClick={() =>
          drawer.openNodeProvenance({ nodeId: "n1", title: "Heat index", restore: mockRestore, showCode: mockShowCode })
        }
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

describe("on a canvas bound to the dataflow's doc, the history is the server's", () => {
  const versions = historyApi.versions as jest.Mock;
  const entries = historyApi.entries as jest.Mock;
  const putBack = historyApi.putBack as jest.Mock;
  const clearBefore = historyApi.clearBefore as jest.Mock;
  const writeCode = historyApi.writeCode as jest.Mock;
  const ana = { kind: "person", account: "1", name: "Ana" };
  const graph = (ids: string[]) => ({
    nodes: ids.map((id, i) => ({ id, type: "acme.none/x@1", x: i * 300, y: 0 })),
    edges: [],
  });
  // A loaded dataflow of one node, Ana's typing, version 2 put back, and a save.
  const answer = (canClear: boolean): ServerVersions => ({
    versions: [
      { id: "p1", parent: null, at: 1_700_000_000_000, kind: "load", what: "", by: null, preview: graph([]) },
      { id: "p2", parent: "p1", at: 1_700_000_000_000, kind: "load", what: "Node added", by: null, preview: graph(["a"]) },
      { id: "p3", parent: "p2", at: 1_700_000_060_000, kind: "typing", what: "Ana edited", by: ana, preview: graph(["a"]) },
      { id: "p4", parent: "p2", at: 1_700_000_120_000, kind: "putBack", what: "Put back", restores: "p2", by: ana, preview: graph(["a"]) },
      { id: "p5", parent: "p4", at: 1_700_000_180_000, kind: "saved", what: "Saved", by: ana, preview: graph(["a"]) },
    ],
    head: "p5",
    kept: true,
    canClear,
  });
  let whenKept: jest.Mock;
  let held: ServerHistory;
  const doc: Record<string, string> = { n1: "df = load()\ndf = df.tail()" };

  beforeEach(() => {
    [versions, entries, putBack, clearBefore, writeCode, mockShowToast, mockShowCode, mockRestore].forEach((m) => m.mockReset());
    whenKept = jest.fn().mockResolvedValue(true);
    held = { projectId: "proj", reads: () => true, whenKept, codeOf: (nodeId: string) => doc[nodeId] };
    act(() => setServerHistory(held));
    mockNodes = [{ id: "n1", data: { code: doc.n1 } }];
  });

  afterEach(() => {
    act(() => setServerHistory(null));
  });

  const titles = () =>
    Array.from(document.querySelectorAll<HTMLElement>("[data-provenance-item]")).map(
      (el) => el.querySelector(".title")!.textContent,
    );

  test("lists the versions every tab of the dataflow lists, named by what made them, the one on the canvas marked", async () => {
    versions.mockResolvedValue(answer(false));
    await openDrawer();
    await waitFor(() => expect(item("p5")).not.toBeNull());
    expect(versions).toHaveBeenCalledWith("proj");
    expect(shownIds()).toEqual(["p1", "p2", "p4", "p5"]);
    expect(titles()).toEqual(["Empty dataflow", "Node added", "Put back version 2", "Saved"]);
    expect(item("p5")).toHaveAttribute("data-provenance-current", "true");
    // Ana's typing, left behind by the put-back, folds under version 2.
    expect(within(item("p2")!.closest("li")!).getByRole("button", { name: /1 version on another branch/ })).toBeInTheDocument();
    fireEvent.click(head("p5"));
    expect(within(item("p5")!).getByText(/^Recorded .+ by Ana$/)).toBeInTheDocument();
    expect(within(item("p5")!).getByText("On the canvas now")).toBeInTheDocument();
  });

  test("its button puts the version back for every tab, after this tab's changes, and reads the history again", async () => {
    versions.mockResolvedValue(answer(false));
    putBack.mockResolvedValue({ refused: [] });
    await openDrawer();
    await waitFor(() => expect(item("p2")).not.toBeNull());
    fireEvent.click(head("p2"));
    fireEvent.click(within(item("p2")!).getByRole("button", { name: "Put this version on the canvas" }));
    await waitFor(() => expect(putBack).toHaveBeenCalledWith("proj", "p2"));
    expect(whenKept.mock.invocationCallOrder[0]).toBeLessThan(putBack.mock.invocationCallOrder[0]);
    await waitFor(() => expect(versions).toHaveBeenCalledTimes(2));
    expect(mockLoadTrill).not.toHaveBeenCalled();
    expect(mockShowToast).not.toHaveBeenCalled();
  });

  test("a put-back that kept someone's code says so", async () => {
    versions.mockResolvedValue(answer(false));
    putBack.mockResolvedValue({ refused: ["a"] });
    await openDrawer();
    await waitFor(() => expect(item("p2")).not.toBeNull());
    fireEvent.click(head("p2"));
    fireEvent.click(within(item("p2")!).getByRole("button", { name: "Put this version on the canvas" }));
    await waitFor(() => expect(mockShowToast).toHaveBeenCalledWith(
      "One node keeps the code someone wrote while this version was put back.", "warning",
    ));
  });

  test("the owner can clear the history before any version but the first, once asked", async () => {
    versions.mockResolvedValue(answer(true));
    clearBefore.mockResolvedValue({ first: "p4", versions: 2 });
    await openDrawer();
    await waitFor(() => expect(item("p4")).not.toBeNull());
    fireEvent.click(head("p1"));
    expect(within(item("p1")!).queryByRole("button", { name: "Clear history before this version" })).toBeNull();
    fireEvent.click(head("p4"));
    fireEvent.click(within(item("p4")!).getByRole("button", { name: "Clear history before this version" }));
    const dialog = await screen.findByRole("dialog", { name: "Clear the history before version 4?" });
    expect(clearBefore).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Clear history" }));
    await waitFor(() => expect(clearBefore).toHaveBeenCalledWith("proj", "p4"));
    await waitFor(() => expect(versions).toHaveBeenCalledTimes(2));
  });

  test("an editor is offered no clearing", async () => {
    versions.mockResolvedValue(answer(false));
    await openDrawer();
    await waitFor(() => expect(item("p4")).not.toBeNull());
    fireEvent.click(head("p4"));
    expect(within(item("p4")!).queryByRole("button", { name: "Clear history before this version" })).toBeNull();
  });

  test("a watcher's tab shows the server's refusal and lists nothing", async () => {
    versions.mockRejectedValue(
      Object.assign(new Error("Only the owner and the editors the owner invited see this dataflow's history."), {
        status: 403,
      }),
    );
    await openDrawer();
    expect(
      await screen.findByText("Only the owner and the editors the owner invited see this dataflow's history."),
    ).toBeInTheDocument();
    expect(shownIds()).toEqual([]);
  });

  test("the drawer reads the history again when the server says it changed", async () => {
    versions.mockResolvedValue(answer(false));
    await openDrawer();
    await waitFor(() => expect(item("p5")).not.toBeNull());
    expect(versions).toHaveBeenCalledTimes(1);
    act(() => mockRemote.get(HISTORY_CHANGED_EVENT)!({ projectId: "proj" }));
    await waitFor(() => expect(versions).toHaveBeenCalledTimes(2));
    // Another dataflow's change is not this one's.
    act(() => mockRemote.get(HISTORY_CHANGED_EVENT)!({ projectId: "other" }));
    expect(versions).toHaveBeenCalledTimes(2);
  });

  describe("a node's entries", () => {
    const entry = (id: number, parentId: number | null, code: string, edit?: string) => ({
      id, parentId, code, inputs: edit ? [] : ["DATAFRAME"], outputs: edit ? [] : ["DATAFRAME"],
      startTime: "2026-10-28T14:05:03Z", endTime: "2026-10-28T14:05:04Z", point: `p${id}`,
      ...(edit ? { kind: "edit" as const, label: edit } : {}),
    });

    async function openRuns() {
      entries.mockResolvedValue({
        entries: [entry(1, null, "df = load()"), entry(2, 1, "df = load()\ndf = df.tail()", "Ana edited")],
        current: 2,
      });
      render(
        <ProvenanceProvider>
          <ProvenanceDrawerProvider>
            <Opener />
          </ProvenanceDrawerProvider>
        </ProvenanceProvider>,
      );
      fireEvent.click(screen.getByRole("button", { name: "Node provenance pill" }));
      await waitFor(() => expect(root()).toHaveAttribute("aria-hidden", "false"));
      await waitFor(() => expect(item("2")).not.toBeNull());
    }

    test("come from the server, the one in use marked", async () => {
      await openRuns();
      expect(entries).toHaveBeenCalledWith("proj", "n1");
      expect(shownIds()).toEqual(["1", "2"]);
      expect(item("2")).toHaveAttribute("data-provenance-current", "true");
      expect(item("2")!.textContent).toMatch(/Ana edited/);
    });

    test("put the code back only if the node still holds what this tab showed, then show the code", async () => {
      writeCode.mockResolvedValue({ ok: true });
      await openRuns();
      fireEvent.click(head("1"));
      fireEvent.click(within(item("1")!).getByRole("button", { name: "Put this code back in the node" }));
      await waitFor(() => expect(writeCode).toHaveBeenCalledWith("proj", "n1", {
        from: "df = load()\ndf = df.tail()", code: "df = load()", label: "Code put back",
      }));
      expect(whenKept.mock.invocationCallOrder[0]).toBeLessThan(writeCode.mock.invocationCallOrder[0]);
      await waitFor(() => expect(mockShowCode).toHaveBeenCalledTimes(1));
      expect(mockRestore).not.toHaveBeenCalled();
    });

    test("a code put back after someone else's change is refused, and the toast says who", async () => {
      writeCode.mockRejectedValue(
        Object.assign(new Error("Ben changed this node after; nothing was undone."), { status: 409 }),
      );
      await openRuns();
      fireEvent.click(head("1"));
      fireEvent.click(within(item("1")!).getByRole("button", { name: "Put this code back in the node" }));
      await waitFor(() => expect(mockShowToast).toHaveBeenCalledWith(
        "Ben changed this node after; nothing was undone.", "warning",
      ));
      expect(mockShowCode).not.toHaveBeenCalled();
      expect(item("2")).toHaveAttribute("data-provenance-current", "true");
    });
  });
});

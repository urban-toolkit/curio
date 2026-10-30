/**
 * Agents at work in the canvas's dock (`AgentDock`, `PeopleHere`,
 * `providers/collab/people.ts`): an agent the server runs in the dataflow's
 * room (`agent_peers.py`) is one more chip in the row, its badge's chip with
 * its glyph in its category's tint, whose tooltip names who asked it, the
 * nodes it is writing and the skills it is using. Whoever asked it sees it
 * too. A canvas agent at work keeps its one chip among the canvas agents,
 * shown at work. A click opens the agent's chat for the owner and the
 * editors, and moves a watcher's view to the node it is writing. The Activity
 * list says when an agent joined, who asked it, and what it did as it left.
 * An agent's `editing` can list several nodes, which the dock and the removal
 * question (`presence.editorsOf`) both read.
 *
 * The awareness is y-protocols' own, fed the updates the server would relay.
 */
import React from "react";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import * as Y from "yjs";
import {
  Awareness,
  applyAwarenessUpdate,
  encodeAwarenessUpdate,
  removeAwarenessStates,
} from "y-protocols/awareness";

const mockSetCenter = jest.fn();
const mockStore: { nodeInternals: Map<string, any> } = { nodeInternals: new Map() };
jest.mock("reactflow", () => ({
  ...jest.requireActual("reactflow"),
  useReactFlow: () => ({
    setCenter: mockSetCenter,
    getZoom: () => 1.5,
    getNode: (id: string) => mockStore.nodeInternals.get(id),
  }),
  useStore: (selector: (state: unknown) => unknown) => selector(mockStore),
}));
let mockCollab: any;
jest.mock("../../providers/CollaborationProvider", () => ({
  useCollab: () => mockCollab,
}));

import { AgentDock } from "../../components/agents/attach/AgentDock";
import { DataflowDocContext } from "../../providers/collab/docContext";
import { NotebookViewContext } from "../../providers/flow/notebookViewContext";
import { peopleOf, samePeople } from "../../providers/collab/people";
import { editorsOf } from "../../providers/collab/presence";

// The room: Ana owns the dataflow and asks the agents; Ben edits; Cal watches.
const ANA = { user_id: 7, username: "ana", name: "Ana", participant_id: "p-ana", role: "owner" };
const BEN = { user_id: 8, username: "ben", name: "Ben Editor", participant_id: "p-ben", role: "editor" };
const CAL = { user_id: 9, username: "cal", name: "Cal Watcher", participant_id: "p-cal", role: "watcher" };

/** An agent at work as the server names it in its state's `user` and in its
 *  Activity entries (`agent_peers.Peer.user`): no account, and who asked it. */
function agentUser(name: string, participantId: string, attachmentId: string, coord: string, category: string) {
  return {
    participant_id: participantId,
    user_id: null,
    name,
    agent: { attachmentId, coord, category, askedBy: { account: "7", name: "Ana" } },
  };
}
const NODE_BUILDER = agentUser("Node Builder", "agent-nb", "att-nb", "agent.curio.node-builder@1", "node");
const DATAFLOW_BUILDER = agentUser("Dataflow Builder", "agent-db", "att-db", "agent.curio.dataflow-builder@1", "canvas");

/** A node on the canvas, as React Flow keeps it: its header's name, its place
 *  and its size. */
function canvasNode(id: string, label: string, x: number, y: number, width: number, height: number) {
  return [id, {
    id,
    data: { nodeType: "curio.builtin/computation-analysis", packageTemplateLabel: label },
    position: { x, y },
    positionAbsolute: { x, y },
    width,
    height,
  }] as [string, any];
}

const made: Awareness[] = [];
function awareness(): Awareness {
  const fresh = new Awareness(new Y.Doc());
  made.push(fresh);
  return fresh;
}

/** This tab's awareness: the one the doc's provider holds. */
let mine: Awareness;

/** Another peer's state reaches this tab, as the server relays it. */
function relay(theirs: Awareness) {
  act(() => applyAwarenessUpdate(mine, encodeAwarenessUpdate(theirs, [theirs.clientID]), "server"));
}

/** Someone else, a tab or an agent at work, is in the room with *state*. */
function joins(state: Record<string, unknown>): Awareness {
  const theirs = awareness();
  theirs.setLocalState(state);
  relay(theirs);
  return theirs;
}

/** A canvas agent of the dataflow, as the dock lists it. */
function att(id: string, name: string, category: string) {
  return {
    attachmentId: id,
    coord: `agent.curio.${name}@1`,
    target: { kind: "canvas" as const },
    sessionId: "s",
    revision: 1,
    intent: null,
    intentEdited: false,
    title: null,
    titleEdited: false,
    name,
    category,
    hooks: ["canvas"],
  };
}

function dock(props: Partial<React.ComponentProps<typeof AgentDock>> = {}, notebookOn = false) {
  return render(
    <NotebookViewContext.Provider value={{ on: notebookOn, laneX: new Map(), cellWidth: 1065, reveal: () => false }}>
      <DataflowDocContext.Provider value={{ provider: { awareness: mine } as any, synced: true }}>
        <AgentDock {...props} />
      </DataflowDocContext.Provider>
    </NotebookViewContext.Provider>,
  );
}

/** The chip in the row of the participant *key*, if any. */
function chipOf(key: string): HTMLElement | null {
  return document.querySelector(`[data-collab-participant="${key}"]`);
}

/** What the chip of *key* says on hover. */
function tooltipOf(key: string): string | null | undefined {
  return chipOf(key)?.closest("[data-tooltip]")?.getAttribute("data-tooltip");
}

/** The row's buttons, by name, without the canvas agents' detach buttons. */
function rowNames(): Array<string | null> {
  const row = screen.getByRole("toolbar", { name: "Canvas agents" });
  return within(row)
    .getAllByRole("button")
    .map((button) => button.getAttribute("aria-label"))
    .filter((name) => !name?.startsWith("Detach"));
}

beforeEach(() => {
  mine = awareness();
  mockSetCenter.mockReset();
  mockStore.nodeInternals = new Map([canvasNode("n-map", "Map Editor", 100, 40, 400, 300)]);
  mockCollab = { participantId: "p-ben", users: [ANA, BEN], activity: [], role: "editor" };
});

afterEach(() => {
  for (const each of made.splice(0)) each.destroy();
});

describe("an agent at work in the canvas's dock", () => {
  test("its chip in the row is its badge's, with its glyph in its category's tint, and names who asked it, the node it writes and the skills it uses", () => {
    joins({ user: NODE_BUILDER, skills: ["map-edits"], editing: "n-map", writes: "code" });
    dock({ onSelect: jest.fn() });

    const said = "Node Builder (asked by Ana), editing Map Editor, using map-edits";
    expect(tooltipOf("agent-nb")).toBe(said);
    const chip = chipOf("agent-nb")!;
    expect(chip).toHaveAttribute("aria-label", said);
    // The badge's chip in its category's tint, which a node's lock chip it
    // holds shares; its glyph, not a person's initials; no color of its own.
    expect(chip.className.split(" ")).toEqual(["avatar", "tint_node"]);
    expect(chip).toHaveAttribute("data-collab-agent", "att-nb");
    expect(chip.textContent).toBe("");
    expect(chip.querySelector("svg")).not.toBeNull();
    expect(chip).not.toHaveAttribute("style");
    // At work, as its badge is: the running dot.
    expect(within(chip).getByRole("img", { name: said })).toHaveClass("runningDot");
  });

  test("whoever asked it sees it too: an agent at work is never yours", () => {
    mockCollab = { participantId: "p-ana", users: [ANA, BEN], activity: [], role: "owner" };
    joins({ user: DATAFLOW_BUILDER, skills: ["catalogs"] });
    dock({ onSelect: jest.fn() });

    expect(tooltipOf("agent-db")).toBe("Dataflow Builder (asked by Ana), using catalogs");
    expect(chipOf("agent-db")).toHaveClass("tint_canvas");

    // Even a state that named the asker's account would not make it theirs:
    // only a person's state can be your own.
    joins({ user: { ...NODE_BUILDER, user_id: 7 }, skills: [] });
    expect(peopleOf(mine, { participantId: "p-ana", userId: 7 }).map((person) => person.name)).toEqual([
      "Dataflow Builder",
      "Node Builder",
    ]);
  });

  test("a canvas agent at work keeps its one chip, shown at work, which still opens its chat", () => {
    mockCollab = { participantId: "p-ana", users: [ANA], activity: [], role: "owner" };
    const onSelect = jest.fn();
    const agent = joins({ user: DATAFLOW_BUILDER, skills: ["catalogs"] });
    dock({ attachments: [att("att-db", "Dataflow Builder", "canvas")], onSelect });

    const said = "Dataflow Builder (asked by Ana), using catalogs";
    const named = Array.from(document.querySelectorAll("[data-tooltip]"))
      .map((element) => element.getAttribute("data-tooltip"))
      .filter((text) => text?.startsWith("Dataflow Builder"));
    expect(named).toEqual([said]);
    expect(chipOf("agent-db")).toBeNull();
    const badge = screen.getByRole("button", { name: "Open chat with Dataflow Builder" });
    expect(badge.closest("[data-tooltip]")).toHaveAttribute("data-agent-at-work", "true");
    expect(badge).toHaveClass("avatar", "tint_canvas");
    expect(within(badge).getByRole("img", { name: said })).toHaveClass("runningDot");
    // Someone else is here, so the row ends with the Activity button.
    expect(rowNames()).toEqual(["Open chat with Dataflow Builder", "Activity"]);

    fireEvent.click(badge);
    expect(onSelect).toHaveBeenCalledWith("att-db");

    // It leaves: its chip is as it was, and nobody else is here.
    act(() => removeAwarenessStates(mine, [agent.clientID], "server"));
    const idle = screen.getByRole("button", { name: "Open chat with Dataflow Builder" });
    expect(idle.closest("[data-tooltip]")).toHaveAttribute("data-tooltip", "Dataflow Builder");
    expect(idle.closest("[data-tooltip]")).not.toHaveAttribute("data-agent-at-work");
    expect(within(idle).queryByRole("img")).toBeNull();
    expect(rowNames()).toEqual(["Open chat with Dataflow Builder"]);
  });

  test.each([
    ["the owner", { participantId: "p-ana", users: [ANA, BEN], role: "owner" }],
    ["an editor", { participantId: "p-ben", users: [ANA, BEN], role: "editor" }],
  ])("for %s, clicking an agent's chip opens its chat", (_who, room) => {
    mockCollab = { ...room, activity: [] };
    const onSelect = jest.fn();
    joins({ user: NODE_BUILDER, skills: ["map-edits"], editing: "n-map", writes: "code" });
    dock({ onSelect });

    fireEvent.click(chipOf("agent-nb")!);

    expect(onSelect).toHaveBeenCalledWith("att-nb");
    expect(mockSetCenter).not.toHaveBeenCalled();
  });

  test("for a watcher, clicking an agent's chip moves the view to the node it writes, else to where it drags", () => {
    mockCollab = { participantId: "p-cal", users: [ANA, CAL], activity: [], role: "watcher" };
    const onSelect = jest.fn();
    const agent = joins({ user: NODE_BUILDER, skills: ["map-edits"], editing: "n-map", writes: "code" });
    dock({ onSelect });

    fireEvent.click(chipOf("agent-nb")!);
    // The middle of the Map Editor node, at the zoom the view has.
    expect(mockSetCenter).toHaveBeenCalledWith(300, 190, { zoom: 1.5, duration: 400 });
    expect(onSelect).not.toHaveBeenCalled();

    // Between writes it drags a node in: the view goes to its drop point.
    agent.setLocalState({
      user: NODE_BUILDER,
      skills: ["map-edits"],
      editing: null,
      writes: null,
      pointer: { x: 640, y: 80, t: 2 },
      carrying: {
        id: "drag-1",
        kind: "add",
        from: { palette: "builtin", item: "curio.builtin/computation-analysis" },
        onto: null,
        node: { type: "curio.builtin/computation-analysis", label: "Filter" },
        ms: 500,
      },
    });
    relay(agent);
    fireEvent.click(chipOf("agent-nb")!);
    expect(mockSetCenter).toHaveBeenLastCalledWith(640, 80, { zoom: 1.5, duration: 400 });
    expect(onSelect).not.toHaveBeenCalled();
  });

  test("the Activity list says when an agent joined and who asked it, and what it did as it left, from a join's snapshot", () => {
    // The room's Activity as a join's snapshot brings it: the server's entries.
    mockCollab = {
      ...mockCollab,
      activity: [
        { kind: "agent_joined", ts: 1, payload: DATAFLOW_BUILDER },
        { kind: "agent_left", ts: 2, payload: { ...DATAFLOW_BUILDER, did: { added: { node: 3, connection: 2 } } } },
        { kind: "agent_joined", ts: 3, payload: NODE_BUILDER },
        { kind: "agent_left", ts: 4, payload: { ...NODE_BUILDER, did: { added: { node: 1, connection: 1 }, changed: { node: 1 } } } },
        { kind: "agent_joined", ts: 5, payload: NODE_BUILDER },
        {
          kind: "agent_left",
          ts: 6,
          payload: { ...NODE_BUILDER, did: { added: { node: 2 }, changed: { node: 1 }, removed: { connection: 1 } } },
        },
        { kind: "agent_joined", ts: 7, payload: NODE_BUILDER },
        { kind: "agent_left", ts: 8, payload: { ...NODE_BUILDER, did: {} } },
      ],
    };
    joins({ user: ANA });
    dock();
    fireEvent.click(screen.getByRole("button", { name: "Activity" }));

    const list = screen.getByRole("region", { name: "Activity" });
    expect(within(list).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "Node Builder left",
      "Node Builder joined, asked by Ana",
      "Node Builder left: added 2 nodes, changed 1 node, and removed 1 connection",
      "Node Builder joined, asked by Ana",
      "Node Builder left: added 1 node and 1 connection, and changed 1 node",
      "Node Builder joined, asked by Ana",
      "Dataflow Builder left: added 3 nodes and 2 connections",
      "Dataflow Builder joined, asked by Ana",
    ]);
  });

  test("an agent writing several nodes at once is editing each of them, for the dock and for the removal question", () => {
    mockStore.nodeInternals = new Map([
      canvasNode("n-load", "Loader", 0, 0, 300, 200),
      canvasNode("n-chart", "Chart", 400, 0, 300, 200),
    ]);
    const agent = joins({ user: NODE_BUILDER, skills: ["map-edits", "widgets"], editing: ["n-load", "n-chart"], writes: "code" });
    joins({ user: ANA, editing: "n-ana" });

    // Removing either node asks first, naming the agent; a person's one node
    // reads as it did.
    expect(editorsOf(mine, "n-load")).toEqual(["Node Builder"]);
    expect(editorsOf(mine, "n-chart")).toEqual(["Node Builder"]);
    expect(editorsOf(mine, "n-ana")).toEqual(["Ana"]);
    expect(editorsOf(mine, "n-other")).toEqual([]);

    const own = { participantId: "p-ben", userId: 8 };
    expect(peopleOf(mine, own).map((person) => [person.name, person.editing])).toEqual([
      ["Ana", ["n-ana"]],
      ["Node Builder", ["n-load", "n-chart"]],
    ]);
    dock({ onSelect: jest.fn() });
    expect(tooltipOf("agent-nb")).toBe("Node Builder (asked by Ana), editing Loader and Chart, using map-edits and widgets");

    // Its drag point moving changes nothing the row draws; its nodes do.
    const before = peopleOf(mine, own);
    agent.setLocalStateField("pointer", { x: 5, y: 6, t: 3 });
    relay(agent);
    expect(samePeople(before, peopleOf(mine, own))).toBe(true);
    agent.setLocalStateField("editing", ["n-load"]);
    relay(agent);
    expect(samePeople(before, peopleOf(mine, own))).toBe(false);
  });
});

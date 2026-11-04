/**
 * Who is here, in the canvas's dock (`AgentDock`, `PeopleHere`,
 * `providers/collab/people.ts`): each other person in the dataflow's room,
 * read from its doc's awareness, as a chip of an agent's shape with their
 * initials in their color, then the Activity button at the row's end. A chip's
 * tooltip names the person, their role and the node they are editing, and a
 * click moves the view to where they point (`pointer`, in flow coordinates).
 * Your own chip is not shown, so with nobody else and no canvas agent the dock
 * is empty, as it was.
 *
 * The awareness is y-protocols' own, fed the updates another tab's would send.
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
  useReactFlow: () => ({ setCenter: mockSetCenter, getZoom: () => 1.5 }),
  useStore: (selector: (state: unknown) => unknown) => selector(mockStore),
}));
let mockCollab: any;
jest.mock("../../providers/CollaborationProvider", () => ({
  useCollab: () => mockCollab,
}));

import { AgentDock } from "../../components/agents/attach/AgentDock";
import { DataflowDocContext } from "../../providers/collab/docContext";
import { NotebookViewContext } from "../../providers/flow/notebookViewContext";
import { PARTICIPANT_COLORS, othersOf, participantColor, remoteCursorStyle } from "../../providers/collab/presence";
import { CursorTracker, pointerOf } from "../../providers/collab/cursors";
import { initialsOf, peopleOf, samePeople } from "../../providers/collab/people";

// The room: Ana, this tab's account, owns the dataflow; Ben edits; Cal watches.
const ANA = { user_id: 7, username: "ana", name: "Ana Owner", participant_id: "p-ana", role: "owner" };
const BEN = { user_id: 8, username: "ben", name: "Ben Editor", participant_id: "p-ben", role: "editor" };
const CAL = { user_id: 9, username: "cal", name: "Cal Watcher", participant_id: "p-cal", role: "watcher" };

const made: Awareness[] = [];
function awareness(): Awareness {
  const fresh = new Awareness(new Y.Doc());
  made.push(fresh);
  return fresh;
}

/** This tab's awareness: the one the doc's provider holds. */
let mine: Awareness;

/** Another tab's state reaches this one, as the server relays it. */
function relay(theirs: Awareness) {
  act(() => applyAwarenessUpdate(mine, encodeAwarenessUpdate(theirs, [theirs.clientID]), "server"));
}

/** Someone else's tab joins with *state*. */
function joins(state: Record<string, unknown>): Awareness {
  const theirs = awareness();
  theirs.setLocalState(state);
  relay(theirs);
  return theirs;
}

function att(id: string, name: string) {
  return {
    attachmentId: id,
    coord: `agent.test.${name}@1`,
    target: { kind: "canvas" as const },
    sessionId: "s",
    revision: 1,
    intent: null,
    intentEdited: false,
    title: null,
    titleEdited: false,
    name,
    category: "node",
    hooks: ["node"],
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

/** The people's chips, in the row's order. */
function chips(): HTMLElement[] {
  const people = screen.getByRole("group", { name: "People here" });
  return within(people).getAllByRole("button").filter((button) => button.hasAttribute("data-collab-participant"));
}

beforeEach(() => {
  mine = awareness();
  mockSetCenter.mockReset();
  mockStore.nodeInternals = new Map();
  mockCollab = { participantId: "p-ana", users: [ANA, BEN, CAL], activity: [] };
});

afterEach(() => {
  for (const each of made.splice(0)) each.destroy();
});

describe("who is here, in the canvas's dock", () => {
  test("with nobody else and no canvas agent, the dock is empty; your own tabs are you", () => {
    const { container } = dock();
    expect(container).toBeEmptyDOMElement();

    // Another tab of this account, and an older state of this tab's own.
    joins({ user: { ...ANA, participant_id: "p-ana-2" } });
    joins({ user: ANA });

    expect(container).toBeEmptyDOMElement();
  });

  test("each other person gets a chip shaped as an agent's, with their initials in their color", () => {
    joins({ user: CAL });
    joins({ user: BEN });
    dock({ attachments: [att("a1", "explainer")] });

    const people = chips();
    expect(people.map((chip) => chip.textContent)).toEqual(["BE", "CW"]);
    // The agents' chip itself: the class an agent's avatar is drawn with.
    const agent = screen.getByRole("button", { name: "Open chat with explainer" });
    expect(agent.className.split(" ")).toContain("avatar");
    expect(people.map((chip) => chip.className)).toEqual(["avatar", "avatar"]);
    // Their color is their account's, as their cursor's is, not their tab's.
    expect(people[0]).toHaveStyle({ color: participantColor("ben") });
    expect(people[1]).toHaveStyle({ color: participantColor("cal") });
    expect(people.map((chip) => chip.getAttribute("data-collab-role"))).toEqual(["editor", "watcher"]);
  });

  test("a chip's tooltip names the person, their role and the node they are editing", () => {
    mockStore.nodeInternals = new Map([
      ["n1", { data: { nodeType: "curio.builtin/computation-analysis", packageTemplateLabel: "Loader" } }],
    ]);
    joins({ user: BEN, editing: "n1" });
    joins({ user: CAL });
    dock();

    const ben = screen.getByRole("button", { name: "Ben Editor (editor), editing Loader" });
    expect(ben.closest("[data-tooltip]")).toHaveAttribute("data-tooltip", "Ben Editor (editor), editing Loader");
    const cal = screen.getByRole("button", { name: "Cal Watcher (watcher)" });
    expect(cal.closest("[data-tooltip]")).toHaveAttribute("data-tooltip", "Cal Watcher (watcher)");
  });

  test("the role is the room's list's, which a change to the editors reaches first", () => {
    joins({ user: CAL });
    mockCollab = { ...mockCollab, users: [ANA, BEN, { ...CAL, role: "editor" }] };
    dock();

    expect(screen.getByRole("button", { name: "Cal Watcher (editor)" })).toHaveAttribute("data-collab-role", "editor");
  });

  test("a participant is their freshest state: one whose doc started again shows once", () => {
    mockStore.nodeInternals = new Map([
      ["n-old", { data: { nodeType: "curio.builtin/computation-analysis", packageTemplateLabel: "Before" } }],
      ["n-new", { data: { nodeType: "curio.builtin/computation-analysis", packageTemplateLabel: "After" } }],
    ]);
    const old = joins({ user: BEN, editing: "n-old" });
    mine.meta.get(old.clientID)!.lastUpdated = Date.now() - 1000;
    joins({ user: BEN, editing: "n-new" });
    dock();

    expect(chips()).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Ben Editor (editor), editing After" })).toBeInTheDocument();
  });

  test("a click moves the view to where they point, at the zoom it has", () => {
    const ben = joins({ user: BEN, pointer: { x: 400, y: 250, t: 1 } });
    dock();

    fireEvent.click(screen.getByRole("button", { name: "Ben Editor (editor)" }));
    expect(mockSetCenter).toHaveBeenCalledWith(400, 250, { zoom: 1.5, duration: 400 });

    // They point elsewhere later: the next click goes there.
    ben.setLocalStateField("pointer", { x: -30, y: 12.5, t: 2 });
    relay(ben);
    fireEvent.click(screen.getByRole("button", { name: "Ben Editor (editor)" }));
    expect(mockSetCenter).toHaveBeenLastCalledWith(-30, 12.5, { zoom: 1.5, duration: 400 });
  });

  test("with reduced motion, the move is at once", () => {
    const matchMedia = window.matchMedia;
    window.matchMedia = ((query: string) => ({ matches: query.includes("prefers-reduced-motion") })) as any;
    try {
      joins({ user: CAL, pointer: { x: 1, y: 2, t: 1 } });
      dock();
      fireEvent.click(screen.getByRole("button", { name: "Cal Watcher (watcher)" }));
      expect(mockSetCenter).toHaveBeenCalledWith(1, 2, { zoom: 1.5, duration: 0 });
    } finally {
      window.matchMedia = matchMedia;
    }
  });

  test.each([
    ["no pointer", {}],
    ["a null pointer, off the canvas", { pointer: null }],
    ["a pointer that is no point", { pointer: { x: "1", y: 2 } }],
    ["a pointer with one coordinate", { pointer: { x: 1 } }],
    ["a field of another name", { cursor: { x: 1, y: 2, t: 1 } }],
  ])("%s is nothing to move to", (_what, fields) => {
    joins({ user: BEN, ...fields });
    dock();

    fireEvent.click(screen.getByRole("button", { name: "Ben Editor (editor)" }));
    expect(mockSetCenter).not.toHaveBeenCalled();
  });

  test("in the notebook view, a click moves nothing: there is no canvas to move over", () => {
    joins({ user: BEN, pointer: { x: 400, y: 250, t: 1 } });
    dock({}, true);

    fireEvent.click(screen.getByRole("button", { name: "Ben Editor (editor)" }));
    expect(mockSetCenter).not.toHaveBeenCalled();
  });

  test("a person who leaves goes from the row, and the dock with nobody left", () => {
    const ben = joins({ user: BEN });
    const { container } = dock();
    expect(chips()).toHaveLength(1);

    act(() => removeAwarenessStates(mine, [ben.clientID], "server"));

    expect(container).toBeEmptyDOMElement();
  });

  test("the canvas agents keep their chips, then come the people, and the Activity button ends the row", () => {
    joins({ user: BEN });
    dock({ attachments: [att("a1", "explainer")], showGoal: true, goal: "", onGoalChange: jest.fn() });

    const row = screen.getByRole("toolbar", { name: "Canvas agents" });
    const named = within(row)
      .getAllByRole("button")
      .map((button) => button.getAttribute("aria-label"))
      .filter((name) => !name?.startsWith("Detach"));
    expect(named).toEqual(["Open chat with explainer", "Ben Editor (editor)", "Activity"]);
    expect(within(row).getByLabelText("Dataflow goal")).toBeInTheDocument();
  });

  test("with canvas agents and nobody else, the row is the agents' alone: no people, no Activity", () => {
    dock({ attachments: [att("a1", "explainer")] });

    expect(screen.getByRole("button", { name: "Open chat with explainer" })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "People here" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Activity" })).toBeNull();
  });

  test("the Activity list holds the room's events, the newest first, and no vote", () => {
    mockCollab = {
      ...mockCollab,
      activity: [
        { kind: "user_joined", ts: 1, payload: { user_id: 7, username: "ana", role: "owner" } },
        { kind: "user_joined", ts: 2, payload: { user_id: 8, username: "ben", role: "editor" } },
        { kind: "role_changed", ts: 3, payload: { user_id: 8, username: "ben", role: "watcher" } },
        { kind: "user_left", ts: 4, payload: { user_id: 10, username: "dee" } },
      ],
    };
    joins({ user: BEN });
    dock();
    const button = screen.getByRole("button", { name: "Activity" });
    expect(button).toHaveAttribute("data-tooltip", "Activity");
    expect(screen.queryByRole("region", { name: "Activity" })).toBeNull();

    fireEvent.click(button);

    expect(button).toHaveAttribute("aria-expanded", "true");
    const list = screen.getByRole("region", { name: "Activity" });
    expect(within(list).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "dee left",
      "Ben Editor is now a watcher",
      "Ben Editor joined (editor)",
      "Ana Owner joined (owner)",
    ]);
    expect(within(list).queryByRole("button")).toBeNull();
    expect(screen.queryByText(/Proposals/)).toBeNull();
    expect(screen.queryByRole("button", { name: /Approve|Reject/ })).toBeNull();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("region", { name: "Activity" })).toBeNull();
  });

  test("a press outside the Activity list closes it", () => {
    joins({ user: BEN });
    dock();
    fireEvent.click(screen.getByRole("button", { name: "Activity" }));
    expect(screen.getByRole("region", { name: "Activity" })).toBeInTheDocument();

    fireEvent.pointerDown(document.body);

    expect(screen.queryByRole("region", { name: "Activity" })).toBeNull();
  });

  test("a read-only canvas's dock sits under its banner", () => {
    joins({ user: BEN });
    dock({ belowBanner: true });

    expect(screen.getByRole("toolbar", { name: "Canvas agents" })).toHaveClass("dock", "dockBelowBanner");
  });
});

// Every guest, and every tab of a Curio with no sign-in, signs in to the one
// shared guest account, so the room numbers its tabs (`room_state.add_user`).
const GUEST = { user_id: 3, username: "guest_shared", name: "Shared Guest", role: "watcher" };
const GUEST_1 = { ...GUEST, participant_id: "p-guest-1", guest_number: 1 };
const GUEST_2 = { ...GUEST, participant_id: "p-guest-2", guest_number: 2 };

/** Everyone else as *own*'s tab reads them: each one's name and color. */
function namesAndColors(own: { participantId: string; userId: number }): string[][] {
  return peopleOf(mine, own).map((person) => [person.name, person.color]);
}

/** Each person's chip in the dock: its name and the initials it shows. */
function labelsAndInitials(): Array<Array<string | null>> {
  return chips().map((chip) => [chip.getAttribute("aria-label"), chip.textContent]);
}

describe("every tab of the shared guest account is someone in the dock", () => {
  test("two tabs of the guest account each see one chip for the other, named and colored by its number", () => {
    // The first guest's tab: the second's state reaches it, and an older one of its own.
    mockCollab = { participantId: "p-guest-1", users: [GUEST_1, GUEST_2], activity: [] };
    joins({ user: GUEST_2, pointer: { x: 5, y: 6, t: 1 } });
    joins({ user: GUEST_1 });

    expect(namesAndColors({ participantId: "p-guest-1", userId: 3 })).toEqual([["Shared Guest 2", PARTICIPANT_COLORS[1]]]);
    const first = dock();
    expect(labelsAndInitials()).toEqual([["Shared Guest 2 (watcher)", "S2"]]);
    expect(chips()[0]).toHaveStyle({ color: PARTICIPANT_COLORS[1] });
    // Its cursor on the canvas and in the code editors says the same.
    const cursors = new CursorTracker().read(othersOf(mine), 0);
    expect(cursors.map((cursor) => [cursor.name, cursor.color])).toEqual([["Shared Guest 2", PARTICIPANT_COLORS[1]]]);
    expect(remoteCursorStyle(mine)).toContain('content: "Shared Guest 2"');
    first.unmount();

    // The second guest's tab sees the first.
    mine = awareness();
    mockCollab = { participantId: "p-guest-2", users: [GUEST_1, GUEST_2], activity: [] };
    joins({ user: GUEST_1 });

    expect(namesAndColors({ participantId: "p-guest-2", userId: 3 })).toEqual([["Shared Guest 1", PARTICIPANT_COLORS[0]]]);
    dock();
    expect(labelsAndInitials()).toEqual([["Shared Guest 1 (watcher)", "S1"]]);
    expect(chips()[0]).toHaveStyle({ color: PARTICIPANT_COLORS[0] });
  });

  test("an account's other tab stays you, while each guest's tab is someone of its own", () => {
    joins({ user: { ...ANA, participant_id: "p-ana-2" } });
    joins({ user: GUEST_2 });
    joins({ user: GUEST_1 });
    mockCollab = { ...mockCollab, users: [ANA, GUEST_1, GUEST_2] };

    expect(namesAndColors({ participantId: "p-ana", userId: 7 })).toEqual([
      ["Shared Guest 1", PARTICIPANT_COLORS[0]],
      ["Shared Guest 2", PARTICIPANT_COLORS[1]],
    ]);
    dock();
    expect(labelsAndInitials()).toEqual([
      ["Shared Guest 1 (watcher)", "S1"],
      ["Shared Guest 2 (watcher)", "S2"],
    ]);
  });

  test("the Activity names a guest's tab by the number its event carries, also once it has left", () => {
    // The first guest's tab has left; the second's is still here.
    const guest = { user_id: 3, username: "guest_shared", name: "Shared Guest" };
    mockCollab = {
      ...mockCollab,
      users: [ANA, GUEST_2],
      activity: [
        { kind: "user_joined", ts: 1, payload: { ...guest, role: "watcher", guest_number: 1 } },
        { kind: "user_joined", ts: 2, payload: { ...guest, role: "watcher", guest_number: 2 } },
        { kind: "user_left", ts: 3, payload: { ...guest, guest_number: 1 } },
      ],
    };
    joins({ user: GUEST_2 });
    dock();
    fireEvent.click(screen.getByRole("button", { name: "Activity" }));

    const list = screen.getByRole("region", { name: "Activity" });
    expect(within(list).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "Shared Guest 1 left",
      "Shared Guest 2 joined (watcher)",
      "Shared Guest 1 joined (watcher)",
    ]);
  });
});

describe("who is who, read from awareness", () => {
  test("initials are the first letters of a name's first and last words, or of its one word", () => {
    expect(["Ana Owner", "Ana María López", "alice", "  ", "Émile zola"].map(initialsOf)).toEqual([
      "AO", "AL", "A", "?", "ÉZ",
    ]);
  });

  test("a pointer is two numbers; anything else is none", () => {
    expect(pointerOf({ pointer: { x: 1, y: -2.5, t: 9 } })).toEqual({ x: 1, y: -2.5, t: 9 });
    expect([
      pointerOf({}),
      pointerOf({ pointer: null }),
      pointerOf({ pointer: { x: Infinity, y: 1 } } as any),
      pointerOf({ cursor: { x: 1, y: 2 } } as any),
      pointerOf(null),
    ]).toEqual([null, null, null, null, null]);
  });

  test("a pointer that moves changes nothing the row draws", () => {
    const ben = joins({ user: BEN, pointer: { x: 1, y: 1, t: 1 } });
    const before = peopleOf(mine, { participantId: "p-ana", userId: 7 });
    ben.setLocalStateField("pointer", { x: 500, y: 9, t: 2 });
    relay(ben);
    const after = peopleOf(mine, { participantId: "p-ana", userId: 7 });

    expect(samePeople(before, after)).toBe(true);
    ben.setLocalStateField("editing", "n1");
    relay(ben);
    expect(samePeople(after, peopleOf(mine, { participantId: "p-ana", userId: 7 }))).toBe(false);
  });
});

/**
 * "Is this me?" in a collaboration room is asked of the participant, never of
 * the account (`providers/collab/participants.ts`). Two tabs of one account,
 * or two hosted guests on the one guest account, share a user id and are two
 * people: each sees the other's lock, and votes on the other's change.
 */
import React from "react";
import { render, screen } from "@testing-library/react";

let mockCollab: any;
jest.mock("../../../providers/CollaborationProvider", () => ({
  useCollab: () => mockCollab,
}));

import {
  canEditRole,
  isOwnParticipant,
  otherEditors,
  roleIn,
} from "../../../providers/collab/participants";
import { CollaborationSidePanel } from "../../../components/collab/CollaborationSidePanel";

// Two tabs of the same account (user 7), and someone watching.
const FIRST_TAB = { user_id: 7, username: "ana", participant_id: "p-1", role: "owner" as const };
const SECOND_TAB = { user_id: 7, username: "ana", participant_id: "p-2", role: "owner" as const };
const WATCHER = { user_id: 9, username: "guest_shared", participant_id: "p-3", role: "watcher" as const };

describe("participants are told apart by participant id", () => {
  test("a lock or proposal of the other tab is not this tab's, though the account is", () => {
    const lock = { user_id: 7, username: "ana", participant_id: "p-1", since: 1 };
    expect(isOwnParticipant("p-1", lock)).toBe(true);
    expect(isOwnParticipant("p-2", lock)).toBe(false);
  });

  test("nothing is this tab's before its join names it", () => {
    expect(isOwnParticipant(null, { participant_id: "p-1" })).toBe(false);
    expect(isOwnParticipant("p-1", { participant_id: undefined })).toBe(false);
  });

  test("a tab's role is its own entry's, not its account's other tab's", () => {
    const users = [FIRST_TAB, { ...SECOND_TAB, role: "editor" as const }, WATCHER];
    expect(roleIn(users, "p-2")).toBe("editor");
    expect(roleIn(users, "p-1")).toBe("owner");
    expect(roleIn(users, "p-9")).toBeNull();
  });

  test("a change waits for the other tab of the same account, and never for a watcher", () => {
    const users = [FIRST_TAB, SECOND_TAB, WATCHER];
    expect(otherEditors(users, "p-1").map((u) => u.participant_id)).toEqual(["p-2"]);
    expect(otherEditors([FIRST_TAB, WATCHER], "p-1")).toEqual([]);
    expect([canEditRole("owner"), canEditRole("editor"), canEditRole("watcher"), canEditRole(null)])
      .toEqual([true, true, false, false]);
  });
});

describe("the collaboration panel votes by participant", () => {
  const proposal = {
    id: "prop-1",
    nodeId: "node-12345678",
    kind: "code",
    oldValue: "a",
    newValue: "b",
    proposed_by: { user_id: 7, username: "ana", participant_id: "p-1" },
    approvals: [],
    rejections: [],
    created_at: 0,
  };
  const panel = (participantId: string, role: string) => {
    mockCollab = {
      enabled: true,
      panelOpen: true,
      users: [FIRST_TAB, SECOND_TAB, WATCHER],
      proposals: [proposal],
      activity: [],
      participantId,
      role,
      approveCodeChange: jest.fn(),
      rejectCodeChange: jest.fn(),
    };
    return render(<CollaborationSidePanel />);
  };

  test("the other tab of the proposer's account may approve or reject it", () => {
    panel("p-2", "owner");
    expect(screen.getByRole("button", { name: "Approve" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Reject" })).toBeTruthy();
  });

  test("the tab that proposed it is not asked to vote on it", () => {
    panel("p-1", "owner");
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
  });

  test("a watcher has no vote", () => {
    panel("p-3", "watcher");
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Reject" })).toBeNull();
  });

  test("the users list names each participant's role", () => {
    const { container } = panel("p-2", "owner");
    const roles = Array.from(container.querySelectorAll("[data-collab-role]")).map((el) => el.textContent);
    expect(roles).toEqual(["owner", "owner", "watcher"]);
  });
});

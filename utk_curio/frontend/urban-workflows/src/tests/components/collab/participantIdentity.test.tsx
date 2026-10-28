/**
 * "Is this me?" in a collaboration room is asked of the participant, never of
 * the account (`providers/collab/participants.ts`). Two tabs of one account,
 * or two hosted guests on the one guest account, share a user id and are two
 * people: each sees the other's lock. Code is typed together in the node's
 * editor, so the room's panel lists people and activity and holds no vote.
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
  roleIn,
} from "../../../providers/collab/participants";
import { CollaborationSidePanel } from "../../../components/collab/CollaborationSidePanel";

// Two tabs of the same account (user 7), and someone watching.
const FIRST_TAB = { user_id: 7, username: "ana", participant_id: "p-1", role: "owner" as const };
const SECOND_TAB = { user_id: 7, username: "ana", participant_id: "p-2", role: "owner" as const };
const WATCHER = { user_id: 9, username: "guest_shared", participant_id: "p-3", role: "watcher" as const };

describe("participants are told apart by participant id", () => {
  test("a lock of the other tab is not this tab's, though the account is", () => {
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

  test("the owner and an editor edit, a watcher does not", () => {
    expect([canEditRole("owner"), canEditRole("editor"), canEditRole("watcher"), canEditRole(null)])
      .toEqual([true, true, false, false]);
  });
});

describe("the collaboration panel", () => {
  const panel = (participantId: string, role: string) => {
    mockCollab = {
      enabled: true,
      panelOpen: true,
      users: [FIRST_TAB, SECOND_TAB, WATCHER],
      activity: [],
      participantId,
      role,
    };
    return render(<CollaborationSidePanel />);
  };

  test("holds no proposals and asks nobody to vote", () => {
    panel("p-2", "owner");
    expect(screen.queryByText(/Proposals/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Reject" })).toBeNull();
    expect(screen.getByText(/Users \(3\)/)).toBeTruthy();
    expect(screen.getByText(/Activity \(0\)/)).toBeTruthy();
  });

  test("the users list names each participant's role", () => {
    const { container } = panel("p-2", "owner");
    const roles = Array.from(container.querySelectorAll("[data-collab-role]")).map((el) => el.textContent);
    expect(roles).toEqual(["owner", "owner", "watcher"]);
  });
});

/**
 * Read-only follows the role (`hook/useSharedView.ts`). An editor the owner
 * invited edits another account's dataflow opened from its link, and anyone
 * else watches it read-only, as a tab does before its room names it. Every
 * gate on editing reads this one rule.
 */
import React from "react";
import { render } from "@testing-library/react";

let mockViewerMode: "owner" | "shared" = "owner";
let mockCollab: any = { role: null };
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ viewerMode: mockViewerMode }),
}));
jest.mock("../../providers/CollaborationProvider", () => ({
  useCollab: () => mockCollab,
}));

import { canvasRole, useSharedView } from "../../hook/useSharedView";

describe("canvasRole", () => {
  test.each([
    // viewerMode, the room's role, the canvas's role
    ["owner", null, "owner"],
    ["owner", "owner", "owner"],
    ["shared", null, "watcher"],
    ["shared", "watcher", "watcher"],
    ["shared", "editor", "editor"],
  ] as const)("%s, room role %s: %s", (viewerMode, role, expected) => {
    expect(canvasRole(viewerMode, { role })).toBe(expected);
  });

  test("a dataflow not saved yet is its owner's", () => {
    expect(canvasRole(undefined, { role: null })).toBe("owner");
  });
});

describe("useSharedView", () => {
  let seen: boolean | undefined;
  const Probe = () => {
    seen = useSharedView();
    return null;
  };

  test.each([
    ["owner", { role: "owner" }, false],
    ["shared", { role: null }, true],
    ["shared", { role: "watcher" }, true],
    ["shared", { role: "editor" }, false],
  ] as const)("%s with %o is read-only: %s", (viewerMode, collab, readOnly) => {
    mockViewerMode = viewerMode;
    mockCollab = collab;
    render(<Probe />);
    expect(seen).toBe(readOnly);
  });
});

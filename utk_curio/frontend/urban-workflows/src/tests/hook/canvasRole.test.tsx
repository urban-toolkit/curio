/**
 * Read-only follows the role (`hook/useSharedView.ts`). With collaboration on,
 * an editor the owner invited edits another account's dataflow opened from
 * its link, and anyone else watches it read-only; with collaboration off,
 * everyone but the owner watches. Every gate on editing reads this one rule.
 */
import React from "react";
import { render } from "@testing-library/react";

let mockViewerMode: "owner" | "shared" = "owner";
let mockCollab: any = { enabled: false, role: null };
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ viewerMode: mockViewerMode }),
}));
jest.mock("../../providers/CollaborationProvider", () => ({
  useCollab: () => mockCollab,
}));

import { canvasRole, useSharedView } from "../../hook/useSharedView";

describe("canvasRole", () => {
  test.each([
    // viewerMode, collaboration on, the room's role, the canvas's role
    ["owner", false, null, "owner"],
    ["owner", true, "owner", "owner"],
    ["shared", false, null, "watcher"],
    ["shared", false, "editor", "watcher"],
    ["shared", true, null, "watcher"],
    ["shared", true, "watcher", "watcher"],
    ["shared", true, "editor", "editor"],
  ] as const)("%s, collaboration %s, room role %s: %s", (viewerMode, enabled, role, expected) => {
    expect(canvasRole(viewerMode, { enabled, role })).toBe(expected);
  });

  test("a dataflow not saved yet is its owner's", () => {
    expect(canvasRole(undefined, { enabled: true, role: null })).toBe("owner");
  });
});

describe("useSharedView", () => {
  let seen: boolean | undefined;
  const Probe = () => {
    seen = useSharedView();
    return null;
  };

  test.each([
    ["owner", { enabled: true, role: "owner" }, false],
    ["shared", { enabled: false, role: null }, true],
    ["shared", { enabled: true, role: "watcher" }, true],
    ["shared", { enabled: true, role: null }, true],
    ["shared", { enabled: true, role: "editor" }, false],
  ] as const)("%s with %o is read-only: %s", (viewerMode, collab, readOnly) => {
    mockViewerMode = viewerMode;
    mockCollab = collab;
    render(<Probe />);
    expect(seen).toBe(readOnly);
  });
});

/**
 * A node or a connection removed on a canvas bound to the dataflow's doc
 * takes the agents attached to it along: the attachments' listing prunes
 * them once the server has the removal (`test_attachments_follow_the_doc.py`),
 * so the dock lists them again then (`refreshAgentsWhenKept`), as it did
 * after the save that pruned them. Every removal on the canvas, this tab's
 * and another's through the doc, goes through it.
 */
import fs from "fs";
import path from "path";

import { refreshAgentsWhenKept } from "../../providers/flow/agentDockAfterRemovals";
import { AGENT_DOCK_REFRESH_EVENT } from "../../services/agents/agentEvents";

let refreshed: jest.Mock;

beforeEach(() => {
  refreshed = jest.fn();
  window.addEventListener(AGENT_DOCK_REFRESH_EVENT, refreshed);
});

afterEach(() => {
  window.removeEventListener(AGENT_DOCK_REFRESH_EVENT, refreshed);
});

test("the dock lists the agents again once the server has the removal, not before", async () => {
  let kept!: (answer: boolean) => void;
  const done = refreshAgentsWhenKept(() => new Promise<boolean>((resolve) => { kept = resolve; }));

  await Promise.resolve();
  expect(refreshed).not.toHaveBeenCalled();

  kept(true);
  await done;
  expect(refreshed).toHaveBeenCalledTimes(1);
});

test("the dock lists them again when the wait gives up or fails, too", async () => {
  await refreshAgentsWhenKept(() => Promise.resolve(false));
  await refreshAgentsWhenKept(() => Promise.reject(new Error("gone")));
  await refreshAgentsWhenKept(undefined);

  expect(refreshed).toHaveBeenCalledTimes(3);
});

test("the canvas's removals of nodes and connections go through it", () => {
  const src = fs.readFileSync(path.resolve(__dirname, "../../providers/FlowProvider.tsx"), "utf8");
  for (const handler of ["onNodesDelete", "onEdgesDelete"]) {
    const at = src.indexOf(`const ${handler} = useCallback(`);
    expect(at).toBeGreaterThan(-1);
    const body = src.slice(at, src.indexOf("}, [", at));
    expect(body).toContain("refreshAgentsWhenKept(docBridgeRef.current?.whenKept)");
  }
});

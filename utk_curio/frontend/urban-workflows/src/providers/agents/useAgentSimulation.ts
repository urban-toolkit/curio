/**
 * Build & validate from the client's side (memo dev/142, F2: extracted from
 * `AgentAttachmentsProvider`): run the driver over the plan that landed (step
 * or auto, dev/67-9), each change that lands reaching a canvas no doc binds,
 * and its current step narrated; cancel.
 */
import { useCallback, useMemo, useState } from "react";

import { agentsApi, bridgeLandedChangeEvent } from "../../services/agents";
import { downloadLine } from "../../utils/downloadLine";

export interface AgentSimulationSlice {
  runSimulation: (attachmentId: string, mode: "step" | "auto") => Promise<Record<string, unknown>>;
  simulationActivity: Record<string, string>;
  /** The build each attachment runs, step or auto, until its stream ends. */
  simulating: Record<string, "step" | "auto">;
  cancelSimulation: (attachmentId: string) => Promise<void>;
}

export function useAgentSimulation(opts: {
  projectRef: React.MutableRefObject<string | null>;
  refreshAfterMutation: (attachmentId: string) => Promise<void>;
}): AgentSimulationSlice {
  const { projectRef, refreshAfterMutation } = opts;
  // dev/67-9: the running simulation's narration line, per attachment.
  const [simulationActivity, setSimulationActivity] = useState<Record<string, string>>({});
  // The build each attachment runs, held here rather than by the plan line
  // that started it: a line drawn again (the chat opened again, or the rail
  // back on the agent) still shows the build, and its Stop.
  const [simulating, setSimulating] = useState<Record<string, "step" | "auto">>({});

  const runSimulation = useCallback(
    async (attachmentId: string, mode: "step" | "auto") => {
      const pid = projectRef.current;
      if (!pid) throw new Error("no project");
      setSimulating((prev) => ({ ...prev, [attachmentId]: mode }));
      const narrate = (line: string | null) =>
        setSimulationActivity((prev) => {
          if (line === null) {
            const { [attachmentId]: _gone, ...rest } = prev;
            return rest;
          }
          return { ...prev, [attachmentId]: line };
        });
      // The node the run executes, as the line said it last, which it says
      // again once that node's downloads on first use are over.
      let executing = "";
      try {
        return await agentsApi.simulate(pid, attachmentId, mode, (name, payload) => {
          if (bridgeLandedChangeEvent(name, payload)) {
            // A validated node's code landed: a canvas no doc binds takes it.
          } else if (name === "stage") {
            narrate(`${String(payload.action)}${payload.label ? `: ${String(payload.label)}` : ""}`);
          } else if (name === "node_executed") {
            executing = `executing upstream ${Number(payload.index) + 1}/${String(payload.total)}`;
            narrate(executing);
          } else if (name === "node_download") {
            // How far what the node reads has downloaded on its first use.
            narrate(downloadLine(payload) ?? executing);
          } else if (name === "generation_round") {
            narrate(`generating content (round ${String(payload.round)})`);
          }
        });
      } finally {
        setSimulating((prev) => {
          const { [attachmentId]: _ended, ...rest } = prev;
          return rest;
        });
        narrate(null);
        await refreshAfterMutation(attachmentId);
      }
    },
    [projectRef, refreshAfterMutation],
  );

  const cancelSimulation = useCallback(async (attachmentId: string) => {
    const pid = projectRef.current;
    if (!pid) return;
    try {
      await agentsApi.cancelSimulate(pid, attachmentId);
    } catch {
      // Nothing running (finished at the boundary first) — fine.
    }
  }, [projectRef]);

  return useMemo(
    () => ({ runSimulation, simulationActivity, simulating, cancelSimulation }),
    [runSimulation, simulationActivity, simulating, cancelSimulation],
  );
}

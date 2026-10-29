/**
 * Build & validate from the client's side (memo dev/142, F2 — extracted from
 * `AgentAttachmentsProvider`): run the driver over the plan that landed (step
 * or auto, dev/67-9), each change that lands reaching a canvas no doc binds,
 * and its current step narrated; cancel.
 */
import { useCallback, useMemo, useState } from "react";

import { agentsApi, bridgeLandedChangeEvent } from "../../services/agents";

export interface AgentSimulationSlice {
  runSimulation: (attachmentId: string, mode: "step" | "auto") => Promise<Record<string, unknown>>;
  simulationActivity: Record<string, string>;
  cancelSimulation: (attachmentId: string) => Promise<void>;
}

export function useAgentSimulation(opts: {
  projectRef: React.MutableRefObject<string | null>;
  refreshAfterMutation: (attachmentId: string) => Promise<void>;
}): AgentSimulationSlice {
  const { projectRef, refreshAfterMutation } = opts;
  // dev/67-9: the running simulation's narration line, per attachment.
  const [simulationActivity, setSimulationActivity] = useState<Record<string, string>>({});

  const runSimulation = useCallback(
    async (attachmentId: string, mode: "step" | "auto") => {
      const pid = projectRef.current;
      if (!pid) throw new Error("no project");
      const narrate = (line: string | null) =>
        setSimulationActivity((prev) => {
          if (line === null) {
            const { [attachmentId]: _gone, ...rest } = prev;
            return rest;
          }
          return { ...prev, [attachmentId]: line };
        });
      try {
        return await agentsApi.simulate(pid, attachmentId, mode, (name, payload) => {
          if (bridgeLandedChangeEvent(name, payload)) {
            // A validated node's code landed: a canvas no doc binds takes it.
          } else if (name === "stage") {
            narrate(`${String(payload.action)}${payload.label ? `: ${String(payload.label)}` : ""}`);
          } else if (name === "node_executed") {
            narrate(`executing upstream ${Number(payload.index) + 1}/${String(payload.total)}`);
          } else if (name === "generation_round") {
            narrate(`generating content (round ${String(payload.round)})`);
          }
        });
      } finally {
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
    () => ({ runSimulation, simulationActivity, cancelSimulation }),
    [runSimulation, simulationActivity, cancelSimulation],
  );
}

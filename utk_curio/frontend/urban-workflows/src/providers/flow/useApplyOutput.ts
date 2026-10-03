// A node's new output, passed on to the nodes it feeds, and the outputs a
// project load restores, passed on the same way.
import type React from "react";
import type { ReactFlowInstance } from "reactflow";
import type { IOutput, NodeExecOutcome } from "./flowTypes";
import type { useGraphEdits } from "./useGraphEdits";

export function useApplyOutput({
    propagateDownstreamInputs, emittedForInputRef, reactFlow, setOutputs,
    markNodeExecutedRef, scheduleInstallSyncRef, signalNodeExecDone,
}: {
    propagateDownstreamInputs: ReturnType<typeof useGraphEdits>["propagateDownstreamInputs"];
    emittedForInputRef: React.MutableRefObject<Map<string, unknown>>;
    reactFlow: ReactFlowInstance;
    setOutputs: (fnOrValue: ((prev: IOutput[]) => IOutput[]) | IOutput[]) => void;
    markNodeExecutedRef: React.MutableRefObject<(nodeId: string) => void>;
    scheduleInstallSyncRef: React.MutableRefObject<(nodeId: string) => void>;
    signalNodeExecDone: (nodeId: string, outcome?: NodeExecOutcome) => void;
}) {
    // a box generated a new output. Propagate it to directly connected boxes
    const applyNewOutput = (newOutput: IOutput) => {
        propagateDownstreamInputs(newOutput.nodeId, newOutput.output, undefined, {
            selectionEcho: newOutput.selectionEcho,
            selectionSource: newOutput.selectionSource,
        });
        emittedForInputRef.current.set(
            newOutput.nodeId,
            reactFlow.getNode(newOutput.nodeId)?.data?.input,
        );

        setOutputs((opts: any) => {
            let added = false;
            const newOpts = opts.map((opt: any) => {
                if (opt.nodeId == newOutput.nodeId) {
                    added = true;
                    return { ...opt, output: newOutput.output };
                }
                return opt;
            });
            if (!added) newOpts.push({ nodeId: newOutput.nodeId, output: newOutput.output });
            return newOpts;
        });

        markNodeExecutedRef.current(newOutput.nodeId);
        // Schedule the install BEFORE signaling done: when this is the last node of
        // the run, signalNodeExecDone → finishPlayAll flushes the debounce, and we
        // need this node already queued so its dataset is included in that flush.
        // Auto-install + surface the produced dataset (debounced, gated to saver
        // producer nodes inside the handler) without a manual save.
        scheduleInstallSyncRef.current(newOutput.nodeId);
        signalNodeExecDone(newOutput.nodeId);
    };

    // Refill downstream `data.input` (incl. merge `in_N` slots) from the outputs
    // restored by a project load. Live propagation only happens on execution and
    // on new connections, so without this every reload leaves inputs empty until
    // the user manually reruns each upstream node (dev/64). Deferred one tick so
    // loadTrill's nodes/edges are committed to the React Flow store first. No
    // exec bookkeeping (signalNodeExecDone / install sync) — nothing executed.
    const hydrateRestoredOutputs = (restored: IOutput[], edges?: readonly any[]) => {
        setTimeout(() => {
            for (const o of restored) {
                if (o?.nodeId && o.output != null && o.output !== "") {
                    propagateDownstreamInputs(o.nodeId, o.output, edges);
                }
            }
        }, 0);
    };

    return { applyNewOutput, hydrateRestoredOutputs };
}

// What a step of a run on the server does to its node, shared by the
// canvas's runs (useServerRun) and a dashboard viewer's (useDashboardRun, #1117):
// the outcome is shown through the setter the node's own run uses, passed
// downstream, and, for a run the tab started, recorded in the provenance.
import React, { useRef } from "react";
import type { Node, ReactFlowInstance } from "reactflow";
import type { NodeOutput } from "../../hook/useNodeState";
import { executionResultOutput, recordExecProvenance } from "../../utils/executionResult";
import { runKeyWithShared, sharedWidgetsOf } from "../../utils/references/sharedParameters";
import type { IOutput } from "./flowTypes";
import type { NodeChange } from "./serverRunSteps";

export function useStepOutcomes({
    reactFlow, setNodes, applyNewOutput, setOutputs, hydrateRestoredOutputs,
    markNodeErroredRef, workflowNameRef, nodeExecProv,
}: {
    reactFlow: ReactFlowInstance;
    setNodes: React.Dispatch<React.SetStateAction<Node[]>>;
    applyNewOutput: (output: IOutput) => void;
    setOutputs: (fnOrValue: ((prev: IOutput[]) => IOutput[]) | IOutput[]) => void;
    hydrateRestoredOutputs: (restored: IOutput[], edges?: readonly any[]) => void;
    markNodeErroredRef: React.MutableRefObject<(nodeId: string) => void>;
    workflowNameRef: React.MutableRefObject<string>;
    nodeExecProv: (...args: any[]) => void;
}) {
    // One count for every outcome shown: a node takes an outcome only when it
    // is newer than the last it took (UniversalNode, `data.serverOutput.seq`).
    const outputSeqRef = useRef(0);

    /**
     * Show *output* on the node, through the same setter its own run uses
     * (UniversalNode). With *onlyIfRunning*, the node shows it only while its
     * own output still reads running: the node holds its current output, which
     * `data.output` mirrors only after it renders.
     *
     * Otherwise the output, and a result's run key, also go on the node's new
     * data, as the node mirrors them once it shows the output (useNodeState):
     * the flow copies a node's data whenever it changes a field, and a copy
     * made before the node renders (a Data Pool handing on an input as the
     * step lands) would keep the outcome from before.
     */
    const showOnNode = (nodeId: string, output: NodeOutput, { onlyIfRunning = false } = {}) => {
        const seq = ++outputSeqRef.current;
        setNodes((nds) => nds.map((node) => {
            if (node.id !== nodeId) return node;
            const data = { ...node.data, serverOutput: { seq, output, onlyIfRunning } };
            if (!onlyIfRunning) {
                data.output = output;
                if (output.code === "success") {
                    data.executedCode = runKeyWithShared(
                        String(data.code ?? ""), data.widgets, sharedWidgetsOf(nds), data.selections,
                    );
                }
            }
            return { ...node, data };
        }));
    };

    /**
     * A step's outcome on its node: shown and passed downstream. *live* is a
     * run this tab started: it also records the provenance, with the step's
     * own times, and its outputs pass on as a run's do. Otherwise the output
     * is restored as a load restores one.
     */
    const showResult = (
        nodeId: string,
        change: Extract<NodeChange, { kind: "result" }>,
        { live }: { live: boolean },
    ) => {
        const node = reactFlow.getNode(nodeId);
        if (!node) return;
        const { shown, artifact } = executionResultOutput(change.reply);
        if (live) {
            const at = (seconds?: number) => (seconds != null ? new Date(seconds * 1000) : new Date());
            recordExecProvenance(nodeExecProv, {
                startedAt: at(change.startedAt),
                finishedAt: at(change.finishedAt),
                workflowName: workflowNameRef.current,
                nodeId,
                input: change.reply?.input ?? "",
                reply: change.reply,
                code: node.data?.code ?? "",
            });
        }
        showOnNode(nodeId, shown);
        if (!artifact) {
            // Nothing passes downstream; the nodes below read "upstream errored" (#347).
            markNodeErroredRef.current(nodeId);
            return;
        }
        if (live) {
            applyNewOutput({ nodeId, output: artifact });
            return;
        }
        // As a load restores an output: passed downstream, nothing saved.
        const restored = { nodeId, output: artifact };
        setOutputs((prev) => [...prev.filter((o) => o.nodeId !== nodeId), restored]);
        hydrateRestoredOutputs([restored]);
    };

    /** A node the run did not run because the node feeding it failed, shown as Run All shows it (#603). */
    const showSkipped = (nodeId: string, reason: string) => {
        markNodeErroredRef.current(nodeId);
        setNodes((nds) => nds.map((node) =>
            node.id === nodeId
                ? { ...node, data: { ...node.data, skipExec: (node.data.skipExec ?? 0) + 1, skipReason: reason } }
                : node,
        ));
    };

    return { showOnNode, showResult, showSkipped };
}

export type StepOutcomes = ReturnType<typeof useStepOutcomes>;

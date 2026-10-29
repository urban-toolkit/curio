import { useCallback } from "react";
import { Node } from "reactflow";

import { useFlowContext } from "../providers/FlowProvider";
import { useProvenanceContext } from "../providers/ProvenanceProvider";
import { PythonInterpreter } from "../PythonInterpreter";
import { JavaScriptInterpreter } from "../JavaScriptInterpreter";
import { TrillGenerator } from "../TrillGenerator";
import { usePosition } from "./usePosition";
import { deoverlapNodes } from "../utils/deoverlapLayout";
import { rekeyNodeProvenance } from "../utils/nodeProvenanceKeys";
import type { SelectionEchoOptions } from "../utils/selectionEcho";
import { runKeyOf } from "../utils/references/runKeys";
import { buildCodeNode, canvasEdgeFromTrill, nodeMetaFromTrill, type CreateCodeNodeOptions } from "./codeNodes";

// Module-level singletons so every node shares the same interpreter
// connection pool. Exported so a node the dataflow's doc brings to this canvas
// (providers/flow/useDataflowDoc.ts) is built with them too.
export const pythonInterpreter = new PythonInterpreter();
export const jsInterpreter = new JavaScriptInterpreter();

/** What a load built, so a caller can hydrate against it. */
export interface LoadedGraph {
    nodes: any[];
    edges: any[];
}

/** `fit: false`: the load leaves the view as it is; the caller frames what it
 *  added (a dropped scenario's box, #769). */
export interface LoadTrillOptions {
    fit?: boolean;
}

interface IUseCode {
    /** Adds a node of *nodeType* to the canvas and returns it. */
    createCodeNode: (nodeType: string, options?: CreateCodeNodeOptions) => Node;
    loadTrill: (
        trill: any,
        suggestionType?: string,
        fromProvenance?: boolean,
        restoredOutputs?: Record<string, string>,
        options?: LoadTrillOptions,
    ) => LoadedGraph;
}

export function useCode(): IUseCode {
    const {
        addNode,
        setOutputs,
        interactionsCallback,
        applyNewPropagation,
        applyNewOutput,
        loadParsedTrill,
        markDirty,
        defaultSaveOutputDataset,
        noteLoadedDataflow,
    } = useFlowContext();
    const { loadNodeProvenance } = useProvenanceContext();
    const { getPosition } = usePosition();

    const outputCallback = useCallback(
        (nodeId: string, output: string, options?: SelectionEchoOptions) => {
            applyNewOutput({nodeId: nodeId, output: output, ...options});
        },
        [setOutputs]
    );

    /**
     * Turn a spec into canvas nodes and edges and hand them to the provider.
     *
     * Returns them as well. Restoring a saved output means pushing it into the
     * nodes downstream of its producer, and the only reliable statement of who
     * those are, at this moment, is the edge list this function just built:
     * React Flow's own store is written from an effect and is a render behind.
     *
     * `restoredOutputs` maps a node id to the saved output a project load
     * restored for it. Those nodes are built as having run, from their current
     * code, so a downstream play reuses them instead of re-running the chain
     * (#407); without it every node counted as never run.
     */
    const loadTrill = (
        trill: any,
        suggestionType?: string,
        fromProvenance?: boolean,
        restoredOutputs?: Record<string, string>,
        options?: LoadTrillOptions,
    ): LoadedGraph => {

        let nodes = [];
        let edges = [];

        for(const node of trill.dataflow.nodes){
            const nodeMeta: any = nodeMetaFromTrill(node, getPosition);

            if(suggestionType != undefined)
                nodeMeta.suggestionType = suggestionType;

            const restored = restoredOutputs?.[node.id];
            if (restored !== undefined) {
                // The same content a run shows (CodeEditor), and the source
                // playNodesUpTo compares against to tell a valid result.
                nodeMeta.output = { code: "success", content: "Saved to file: " + restored };
                nodeMeta.executedCode = runKeyOf(node.content, nodeMeta.widgets, nodeMeta.selections);
            }

            nodes.push(generateCodeNode(node.type, nodeMeta));

        }

        // Nothing else corrects layout: the loop above copies the spec's x/y
        // straight onto the canvas, so a legacy file or a hand-edited spec can
        // render with its boxes on top of each other. Separating them here
        // covers every way a dataflow reaches the canvas - opening a project,
        // a shared link, File -> Load, and the revert branch below - because
        // all four build their nodes through this one loop.
        //
        // It must happen BEFORE loadParsedTrill: rewriting positions after the
        // nodes are in the React Flow store would emit `position` changes,
        // which MainCanvas treats as an edit and would mark every project dirty
        // on open (#229). Pre-mount there is no change to emit.
        //
        // Skipped for a suggestion, which is a subset merged into a live graph:
        // separating it in isolation would miss every collision with what is
        // already on canvas and drag the suggestion off the node it explains.
        if (suggestionType === undefined) {
            nodes = deoverlapNodes(nodes);
        }

        for(const edge of trill.dataflow.edges){
            edges.push(canvasEdgeFromTrill(edge, suggestionType));
        }

        if (fromProvenance) {
            // Reverting to a historical version: preserve the current provenance graph.
            // latestTrill was already set to the target version by switchProvenanceTrill.
            const savedProv = TrillGenerator.getSerializableDataflowProvenance();
            // #662: a snapshot carries scenarios only when it had some, so an
            // absent key restores none.
            loadParsedTrill(trill.dataflow.name, trill.dataflow.task, nodes, edges, false, false, trill.dataflow.packages || [], trill.dataflow.description || "", trill.dataflow.datasets || [], undefined, trill.dataflow.scenarios ?? [], options?.fit);
            TrillGenerator.loadDataflowProvenance(savedProv);
            // Reverting puts a DIFFERENT graph on the canvas than the one on
            // disk, so it is an edit. The edge replay inside loadParsedTrill no
            // longer says so (#229), and this branch is the only place the
            // revert is still distinguishable from opening a project - both
            // reach loadParsedTrill identically from there down.
            markDirty();
        } else if(suggestionType == undefined) {
            // #845: a dataflow without the key has auto-run off.
            loadParsedTrill(trill.dataflow.name, trill.dataflow.task, nodes, edges, true, false, trill.dataflow.packages || [], trill.dataflow.description || "", trill.dataflow.datasets || [], trill.dataflow.categories || {}, trill.dataflow.scenarios ?? [], options?.fit, trill.dataflow.autoRun === true);
            // What the canvas holds now, for its binding to the dataflow's doc.
            noteLoadedDataflow?.(trill.dataflow);
            // Each node's next run or edit branches from its entry that holds
            // the code it loaded with.
            if (trill.nodeProvenance) {
                loadNodeProvenance(
                    rekeyNodeProvenance(trill.nodeProvenance, nodes.map((n) => n.id)),
                    Object.fromEntries(nodes.map((n) => [n.id, typeof n.data?.code === "string" ? n.data.code : ""])),
                );
            }
            if (trill.dataflowProvenance) TrillGenerator.loadDataflowProvenance(trill.dataflowProvenance);
        } else {
            loadParsedTrill(trill.dataflow.name, trill.dataflow.task, nodes, edges, false, true, undefined, trill.dataflow.description || "", trill.dataflow.datasets || [], undefined, undefined, options?.fit);
        }

        return { nodes, edges };
    }

    const generateCodeNode = useCallback((nodeType: string, options: CreateCodeNodeOptions = {}): Node =>
        buildCodeNode(nodeType, options, {
            pythonInterpreter,
            jsInterpreter,
            outputCallback,
            interactionsCallback,
            propagationCallback: applyNewPropagation,
            defaultSaveOutputDataset,
            position: getPosition,
        }),
    [addNode, outputCallback, getPosition, defaultSaveOutputDataset]);

    const createCodeNode = useCallback((nodeType: string, options: CreateCodeNodeOptions = {}) => {
        let node = generateCodeNode(nodeType, options);
        addNode(node, undefined, true);
        return node;
    }, [addNode, outputCallback, getPosition]);

    return { createCodeNode, loadTrill };
}

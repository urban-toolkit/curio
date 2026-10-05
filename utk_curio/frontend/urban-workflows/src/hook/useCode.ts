import { useCallback } from "react";
import { Node } from "reactflow";
import { v4 as uuid } from "uuid";

import { useFlowContext } from "../providers/FlowProvider";
import { useProvenanceContext } from "../providers/ProvenanceProvider";
import { PythonInterpreter } from "../PythonInterpreter";
import { JavaScriptInterpreter } from "../JavaScriptInterpreter";
import { TrillGenerator } from "../TrillGenerator";
import { usePosition } from "./usePosition";
import { AccessLevelType, EdgeType, CURIO_UNIVERSAL_NODE_TYPE } from "../constants";
import { DatasetNodeSource } from "../services/datasetCatalog";
import { deoverlapNodes } from "../utils/deoverlapLayout";
import { rekeyNodeProvenance } from "../utils/nodeProvenanceKeys";
import type { SelectionEchoOptions } from "../utils/selectionEcho";
import type { CanvasTemplateConfig } from "../utils/canvasTemplateConfig";
import { canvasTemplateConfigFromSpec } from "../utils/canvasTemplateConfigSpec";
import { dataPoolFromSpec } from "../utils/dataPoolSpec";
import { normalizeWidgets, type WidgetDef } from "../utils/widgets/widgetModel";
import { runKeyWithShared, sharedWidgetsOfSpec } from "../utils/references/sharedParameters";
import { normalizeSelections, type SelectionTag } from "../utils/references/selectionTags";
import { lineageFromSpec } from "../utils/scenarios/duplicateSelection";

// Module-level singletons so every node shares the same interpreter
// connection pool. Exported so collaboration's remote-graph handler can
// re-attach them to nodes that arrive over the socket (which strips
// non-serializable fields).
export const pythonInterpreter = new PythonInterpreter();
export const jsInterpreter = new JavaScriptInterpreter();

type CreateCodeNodeOptions = {
    nodeId?: string;
    code?: string;
    description?: string;
    templateId?: string;
    templateName?: string;
    accessLevel?: AccessLevelType;
    customTemplate?: boolean;
    position?: { x: number; y: number };
    suggestionType?: boolean;
    goal?: string;
    warnings?: string[];
    inType?: string;
    out?: string;
    keywords?: number[];
    nodeWidth?: number;
    nodeHeight?: number;
    dashboardPinned?: boolean;
    dashboardX?: number;
    dashboardY?: number;
    dashboardWidth?: number;
    dashboardHeight?: number;
    datasetRefs?: string[];
    appliedDatasets?: Record<string, unknown>;
    datasetSource?: DatasetNodeSource;
    // The model a Model Catalog drop set (canonical shape metadata.modelRefs).
    modelRefs?: { id: string; name: string }[];
    saveOutputDataset?: boolean;
    // dev/89: per-node appearance (canonical spec shape metadata.appearance;
    // normalized values only — validation is utils/nodeAppearance's job).
    appearance?: { backgroundColor?: string };
    // dev/89: optional display title (post-it header et al.).
    title?: string;
    // #237: persisted per-node comments (canonical shape metadata.comments).
    // Opaque here - utils/nodeComments owns the mapping to live IComment.
    comments?: unknown[];
    // #262: the Spatial Join's polygon property (canonical shape
    // metadata.spatialJoin). #276: Simple View's image column
    // (metadata.simpleVis). Both were read off the spec in loadTrill and then
    // dropped here, because this factory builds node data from an explicit
    // list: the setting survived a save and never a load.
    spatialJoin?: { nameProperty?: string; output?: "points" | "polygons" };
    simpleVis?: { imageColumn?: string };
    // #412: a renamed node header (metadata.packageTemplateLabel), which the
    // header reads through resolveNodeDisplayLabel.
    packageTemplateLabel?: string;
    // #412: the rest of what the node settings modal saved
    // (metadata.packageTemplateConfig), which the editor tabs read.
    packageTemplateConfig?: Partial<CanvasTemplateConfig>;
    // #581: a Data Pool's conflict modes (metadata.dataPool).
    dataPool?: { insideChart?: string; betweenCharts?: string };
    // #662: the node's widgets and their values (metadata.widgets).
    widgets?: WidgetDef[];
    // #662: the ids a copy descends from, oldest first (metadata.copiedFrom).
    copiedFrom?: string[];
    // #662: the node's selection tags and the ids they hold (metadata.selections).
    selections?: SelectionTag[];
    // #407: a node whose saved output a project load restored mounts as having
    // run: the output it shows, and the source that produced it.
    output?: { code: string; content: string };
    executedCode?: string;
};

/** What a load built, so a caller can hydrate against it. */
export interface LoadedGraph {
    nodes: any[];
    edges: any[];
}

interface IUseCode {
    createCodeNode: (nodeType: string, options?: CreateCodeNodeOptions) => void;
    loadTrill: (
        trill: any,
        suggestionType?: string,
        fromProvenance?: boolean,
        restoredOutputs?: Record<string, string>,
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
    ): LoadedGraph => {

        let nodes = [];
        let edges = [];
        // #662: the Parameter nodes' widgets, which a restored output's run
        // key covers, as a run's does.
        const shared = sharedWidgetsOfSpec(trill.dataflow.nodes);

        for(const node of trill.dataflow.nodes){
            let x = node.x;
            let y = node.y;
            const parsedWidth =
                typeof node.width === "number"
                    ? node.width
                    : typeof node.nodeWidth === "number"
                        ? node.nodeWidth
                        : typeof node.metadata?.width === "number"
                            ? node.metadata.width
                            : typeof node.metadata?.nodeWidth === "number"
                                ? node.metadata.nodeWidth
                                : undefined;
            const parsedHeight =
                typeof node.height === "number"
                    ? node.height
                    : typeof node.nodeHeight === "number"
                        ? node.nodeHeight
                        : typeof node.metadata?.height === "number"
                            ? node.metadata.height
                            : typeof node.metadata?.nodeHeight === "number"
                                ? node.metadata.nodeHeight
                                : undefined;

            if(x == undefined || y == undefined){
                let position = getPosition();
                x = position.x + 800;
                y = position.y;
            }

            let nodeMeta: any = {
                nodeId: node.id, 
                code: node.content, 
                position: {x: x, y: y}
            }

            if(node.goal != undefined)
                nodeMeta.goal = node.goal;

            if(node.in != undefined)
                nodeMeta.inType = node.in;

            if(node.out != undefined)
                nodeMeta.out = node.out;

            if(node.warnings != undefined)
                nodeMeta.warnings = node.warnings;

            if(node.metadata != undefined && node.metadata.keywords != undefined)
                nodeMeta.keywords = node.metadata.keywords;

            if(node.metadata != undefined && Array.isArray(node.metadata.datasetRefs))
                nodeMeta.datasetRefs = node.metadata.datasetRefs;

            if(node.metadata != undefined && node.metadata.datasetSource != undefined)
                nodeMeta.datasetSource = node.metadata.datasetSource;

            if(node.metadata != undefined && Array.isArray(node.metadata.modelRefs))
                nodeMeta.modelRefs = node.metadata.modelRefs;

            // dev/89: the canonical per-node appearance round-trips into live
            // data (rendered via utils/nodeAppearance — invalid legacy values
            // fall back at render, never here).
            if(node.metadata != undefined && node.metadata.appearance != undefined)
                nodeMeta.appearance = node.metadata.appearance;

            // #237: comments round-trip through the canvas node's data, which
            // is what NodeContainer renders and what TrillGenerator re-reads.
            if(node.metadata != undefined && Array.isArray(node.metadata.comments))
                nodeMeta.comments = node.metadata.comments;

            // #262: the Spatial Join's polygon property round-trips into node data.
            if(node.metadata != undefined && node.metadata.spatialJoin != undefined)
                nodeMeta.spatialJoin = node.metadata.spatialJoin;

            // #276: the Simple View's chosen image column round-trips too.
            if(node.metadata != undefined && node.metadata.simpleVis != undefined)
                nodeMeta.simpleVis = node.metadata.simpleVis;

            // #412: and so does a renamed node header.
            if(node.metadata != undefined && typeof node.metadata.packageTemplateLabel === "string")
                nodeMeta.packageTemplateLabel = node.metadata.packageTemplateLabel;

            // #412: and the rest of the node settings config, with fresh port ids.
            if(node.metadata != undefined && node.metadata.packageTemplateConfig != undefined)
                nodeMeta.packageTemplateConfig = canvasTemplateConfigFromSpec(node.metadata.packageTemplateConfig);

            // #581: and a Data Pool's conflict modes, the ones that name a mode.
            if(node.metadata != undefined && node.metadata.dataPool != undefined)
                nodeMeta.dataPool = dataPoolFromSpec(node.metadata.dataPool);

            // #662: and the node's widgets, with the values they were saved with.
            if(node.metadata != undefined && Array.isArray(node.metadata.widgets))
                nodeMeta.widgets = normalizeWidgets(node.metadata.widgets);

            // #662: and the lineage of a copy Duplicate selection made.
            if(node.metadata != undefined && Array.isArray(node.metadata.copiedFrom))
                nodeMeta.copiedFrom = lineageFromSpec(node.metadata.copiedFrom);

            // #662: and the node's selection tags, with the ids they held.
            if(node.metadata != undefined && Array.isArray(node.metadata.selections))
                nodeMeta.selections = normalizeSelections(node.metadata.selections);

            if(typeof node.title === "string" && node.title)
                nodeMeta.title = node.title;

            if(typeof parsedWidth === "number")
                nodeMeta.nodeWidth = parsedWidth;

            if(typeof parsedHeight === "number")
                nodeMeta.nodeHeight = parsedHeight;

            if(node.dashboardPinned)
                nodeMeta.dashboardPinned = true;

            if(typeof node.dashboardX === "number"){
                nodeMeta.dashboardX = node.dashboardX;
                nodeMeta.dashboardY = node.dashboardY;
            }

            if(typeof node.dashboardWidth === "number"){
                nodeMeta.dashboardWidth = node.dashboardWidth;
                nodeMeta.dashboardHeight = node.dashboardHeight;
            }

            if(typeof node.saveOutputDataset === "boolean")
                nodeMeta.saveOutputDataset = node.saveOutputDataset;

            if(suggestionType != undefined)
                nodeMeta.suggestionType = suggestionType;

            const restored = restoredOutputs?.[node.id];
            if (restored !== undefined) {
                // The same content a run shows (CodeEditor), and the source
                // playNodesUpTo compares against to tell a valid result.
                nodeMeta.output = { code: "success", content: "Saved to file: " + restored };
                nodeMeta.executedCode = runKeyWithShared(node.content, nodeMeta.widgets, shared, nodeMeta.selections);
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

            // Respect explicit handle ids in the spec (named handles like
            // `in_points` / `in_polygons` on spatial-join). Fall back to the
            // legacy `in_N` suffix of the edge id, then to the default "in"
            // handle, as `named_input_slot` reads them in the runner.
            let targetHandle = edge.targetHandle || "in";
            if (!edge.targetHandle) {
                const legacy = typeof edge.id === "string" ? edge.id.match(/in_(\d+)$/) : null;
                if (legacy) targetHandle = "in_" + legacy[1];
            }

            let add_edge: any = {
                id: edge.id,
                type: EdgeType.UNIDIRECTIONAL_EDGE,
                markerEnd: {type: "arrow"},
                source: edge.source,
                sourceHandle: edge.sourceHandle || "out",
                target: edge.target,
                targetHandle
            }

            add_edge.data = {}

            if(suggestionType != undefined)
                add_edge.data.suggestionType = suggestionType;

            if(edge.metadata != undefined && edge.metadata.keywords != undefined)
                add_edge.data.keywords = edge.metadata.keywords;

            if(edge.type == "Interaction"){
                add_edge.markerStart = {type: "arrow"};
                add_edge.sourceHandle = "in/out";
                add_edge.targetHandle = "in/out";
                add_edge.type = EdgeType.BIDIRECTIONAL_EDGE;
            }

            edges.push(add_edge);
        }

        if (fromProvenance) {
            // Reverting to a historical version: preserve the current provenance graph.
            // latestTrill was already set to the target version by switchProvenanceTrill.
            const savedProv = TrillGenerator.getSerializableDataflowProvenance();
            // #662: a snapshot carries scenarios only when it had some, so an
            // absent key restores none.
            loadParsedTrill(trill.dataflow.name, trill.dataflow.task, nodes, edges, false, false, trill.dataflow.packages || [], trill.dataflow.description || "", trill.dataflow.datasets || [], undefined, trill.dataflow.scenarios ?? []);
            TrillGenerator.loadDataflowProvenance(savedProv);
            // Reverting puts a DIFFERENT graph on the canvas than the one on
            // disk, so it is an edit. The edge replay inside loadParsedTrill no
            // longer says so (#229), and this branch is the only place the
            // revert is still distinguishable from opening a project - both
            // reach loadParsedTrill identically from there down.
            markDirty();
        } else if(suggestionType == undefined) {
            loadParsedTrill(trill.dataflow.name, trill.dataflow.task, nodes, edges, true, false, trill.dataflow.packages || [], trill.dataflow.description || "", trill.dataflow.datasets || [], trill.dataflow.categories || {}, trill.dataflow.scenarios ?? []);
            if (trill.nodeProvenance) loadNodeProvenance(rekeyNodeProvenance(trill.nodeProvenance, nodes.map((n) => n.id)));
            if (trill.dataflowProvenance) TrillGenerator.loadDataflowProvenance(trill.dataflowProvenance);
        } else {
            loadParsedTrill(trill.dataflow.name, trill.dataflow.task, nodes, edges, false, true, undefined, trill.dataflow.description || "", trill.dataflow.datasets || []);
        }

        return { nodes, edges };
    }

    const generateCodeNode = useCallback((nodeType: string, options: CreateCodeNodeOptions = {}) => {
        const {
            nodeId = uuid(),
            code = undefined,
            description = undefined,
            templateId = undefined,
            templateName = undefined,
            accessLevel = undefined,
            customTemplate = undefined,
            position = getPosition(),
            suggestionType = "none",
            warnings = [],
            goal = "",
            inType = "DEFAULT",
            out = "DEFAULT",
            keywords = [],
            nodeWidth = undefined,
            nodeHeight = undefined,
            dashboardPinned = undefined,
            dashboardX = undefined,
            dashboardY = undefined,
            dashboardWidth = undefined,
            dashboardHeight = undefined,
            datasetRefs = undefined,
            appliedDatasets = undefined,
            datasetSource = undefined,
            modelRefs = undefined,
            saveOutputDataset = undefined,
            appearance = undefined,
            title = undefined,
            comments = undefined,
            spatialJoin = undefined,
            simpleVis = undefined,
            packageTemplateLabel = undefined,
            packageTemplateConfig = undefined,
            dataPool = undefined,
            widgets = undefined,
            copiedFrom = undefined,
            selections = undefined,
            output = undefined,
            executedCode = undefined,
        } = options;

        const node: Node = {
            id: nodeId,
            type: CURIO_UNIVERSAL_NODE_TYPE,
            position,
            data: {
                nodeId: nodeId,
                pythonInterpreter: pythonInterpreter,
                jsInterpreter: jsInterpreter,
                defaultCode: code,
                // The serializer (TrillGenerator) reads ``data.code``; seed it
                // with the provided content so a programmatically-created node
                // round-trips through save without an editor touch (dev/51).
                // ``undefined`` when no code is given — palette drops unchanged.
                code: code,
                description,
                templateId,
                templateName,
                accessLevel,
                warnings,
                hidden: false,
                nodeType: nodeType,
                customTemplate,
                suggestionType,
                goal,
                in: inType,
                out,
                nodeWidth,
                nodeHeight,
                dashboardPinned,
                dashboardX,
                dashboardY,
                dashboardWidth,
                dashboardHeight,
                datasetRefs,
                appliedDatasets,
                datasetSource,
                appearance,
                title,
                comments,
                spatialJoin,
                simpleVis,
                packageTemplateLabel,
                packageTemplateConfig,
                dataPool,
                widgets,
                copiedFrom,
                selections,
                saveOutputDataset:
                    saveOutputDataset !== undefined
                        ? saveOutputDataset
                        : defaultSaveOutputDataset,
                input: "",
                inputTypes: [],
                keywords,
                outputCallback,
                interactionsCallback,
                propagationCallback: applyNewPropagation,
                ...(output !== undefined ? { output } : {}),
                ...(executedCode !== undefined ? { executedCode } : {}),
                ...(modelRefs !== undefined ? { modelRefs } : {}),
            },
        };

        return node;

    }, [addNode, outputCallback, getPosition, defaultSaveOutputDataset]);

    const createCodeNode = useCallback((nodeType: string, options: CreateCodeNodeOptions = {}) => {
        let node = generateCodeNode(nodeType, options);
        addNode(node, undefined, true);
        return node;
    }, [addNode, outputCallback, getPosition]);

    return { createCodeNode, loadTrill };
}

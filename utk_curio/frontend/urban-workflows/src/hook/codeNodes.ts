/**
 * A canvas node and edge made from their Trill, the one way: a load builds its
 * nodes and edges here (`useCode`'s `loadTrill`), and so does the dataflow's
 * doc when a change reaches this tab (`providers/flow/useDataflowDoc.ts`).
 * `TrillGenerator.generateTrill` is the way back.
 */
import type { Node } from "reactflow";
import { v4 as uuid } from "uuid";

import { AccessLevelType, CURIO_UNIVERSAL_NODE_TYPE, EdgeType } from "../constants";
import type { DatasetNodeSource } from "../services/datasetCatalog";
import type { CanvasTemplateConfig } from "../utils/canvasTemplateConfig";
import { canvasTemplateConfigFromSpec } from "../utils/canvasTemplateConfigSpec";
import { dataPoolFromSpec } from "../utils/dataPoolSpec";
import { normalizeWidgets, type WidgetDef } from "../utils/widgets/widgetModel";
import { normalizeSelections, type SelectionTag } from "../utils/references/selectionTags";
import { lineageFromSpec } from "../utils/scenarios/duplicateSelection";

export type CreateCodeNodeOptions = {
    nodeId?: string;
    code?: string;
    description?: string;
    templateId?: string;
    templateName?: string;
    accessLevel?: AccessLevelType;
    customTemplate?: boolean;
    position?: { x: number; y: number };
    suggestionType?: boolean | string;
    goal?: string;
    warnings?: string[];
    inType?: string;
    out?: string;
    keywords?: number[];
    nodeWidth?: number;
    nodeHeight?: number;
    // Folded to its chip on the canvas (spec `minimized`).
    minimized?: boolean;
    dashboardPinned?: boolean;
    dashboardX?: number;
    dashboardY?: number;
    dashboardWidth?: number;
    dashboardHeight?: number;
    datasetRefs?: string[];
    appliedDatasets?: Record<string, unknown>;
    datasetSource?: DatasetNodeSource;
    // What each dataset widget was set to by a drop, and the refs it bound
    // (canonical shape metadata.datasetWidgets; datasetApplication).
    datasetWidgets?: Record<string, unknown>;
    // The model a Model Catalog drop set (canonical shape metadata.modelRefs).
    modelRefs?: { id: string; name: string }[];
    saveOutputDataset?: boolean;
    // dev/89: per-node appearance (canonical spec shape metadata.appearance;
    // normalized values only — validation is utils/nodeAppearance's job).
    appearance?: { backgroundColor?: string };
    // dev/89: optional display title (post-it header et al.).
    title?: string;
    // #576: the Spatial Join's operation and output (canonical shape
    // metadata.spatialJoin). #276: Simple View's image column
    // (metadata.simpleVis). Both were read off the spec in loadTrill and then
    // dropped here, because this factory builds node data from an explicit
    // list: the setting survived a save and never a load.
    spatialJoin?: { predicate?: string; output?: "pairs" | "counts" };
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

/** What a node's data holds besides its Trill: the callbacks and the
 *  interpreters every node of the canvas shares. */
export interface CodeNodeRuntime {
    pythonInterpreter: unknown;
    jsInterpreter: unknown;
    outputCallback: unknown;
    interactionsCallback: unknown;
    propagationCallback: unknown;
    /** The deployment's default for a node's "Save output dataset". */
    defaultSaveOutputDataset: boolean;
    /** Where a node with no place of its own goes. */
    position: () => { x: number; y: number };
}

/**
 * The options a Trill node is built with: its place, code and every setting
 * the spec holds for it. *fallbackPosition* places a node the spec gives no
 * place.
 */
export function nodeMetaFromTrill(node: any, fallbackPosition: () => { x: number; y: number }): CreateCodeNodeOptions {
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

    if (x == undefined || y == undefined) {
        const position = fallbackPosition();
        x = position.x + 800;
        y = position.y;
    }

    const nodeMeta: any = {
        nodeId: node.id,
        code: node.content,
        position: { x: x, y: y },
    };

    if (node.goal != undefined)
        nodeMeta.goal = node.goal;

    if (node.in != undefined)
        nodeMeta.inType = node.in;

    if (node.out != undefined)
        nodeMeta.out = node.out;

    if (node.warnings != undefined)
        nodeMeta.warnings = node.warnings;

    if (node.metadata != undefined && node.metadata.keywords != undefined)
        nodeMeta.keywords = node.metadata.keywords;

    if (node.metadata != undefined && Array.isArray(node.metadata.datasetRefs))
        nodeMeta.datasetRefs = node.metadata.datasetRefs;

    if (node.metadata != undefined && node.metadata.datasetSource != undefined)
        nodeMeta.datasetSource = node.metadata.datasetSource;

    // What each dataset widget was set to, so the next drop takes the
    // place of the refs it bound.
    if (node.metadata != undefined && node.metadata.datasetWidgets != undefined
        && typeof node.metadata.datasetWidgets === "object" && !Array.isArray(node.metadata.datasetWidgets))
        nodeMeta.datasetWidgets = node.metadata.datasetWidgets;

    if (node.metadata != undefined && Array.isArray(node.metadata.modelRefs))
        nodeMeta.modelRefs = node.metadata.modelRefs;

    // dev/89: the canonical per-node appearance round-trips into live
    // data (rendered via utils/nodeAppearance — invalid legacy values
    // fall back at render, never here).
    if (node.metadata != undefined && node.metadata.appearance != undefined)
        nodeMeta.appearance = node.metadata.appearance;

    // #262: the Spatial Join's polygon property round-trips into node data.
    if (node.metadata != undefined && node.metadata.spatialJoin != undefined)
        nodeMeta.spatialJoin = node.metadata.spatialJoin;

    // #276: the Simple View's chosen image column round-trips too.
    if (node.metadata != undefined && node.metadata.simpleVis != undefined)
        nodeMeta.simpleVis = node.metadata.simpleVis;

    // #412: and so does a renamed node header.
    if (node.metadata != undefined && typeof node.metadata.packageTemplateLabel === "string")
        nodeMeta.packageTemplateLabel = node.metadata.packageTemplateLabel;

    // #412: and the rest of the node settings config, with fresh port ids.
    if (node.metadata != undefined && node.metadata.packageTemplateConfig != undefined)
        nodeMeta.packageTemplateConfig = canvasTemplateConfigFromSpec(node.metadata.packageTemplateConfig);

    // #581: and a Data Pool's conflict modes, the ones that name a mode.
    if (node.metadata != undefined && node.metadata.dataPool != undefined)
        nodeMeta.dataPool = dataPoolFromSpec(node.metadata.dataPool);

    // #662: and the node's widgets, with the values they were saved with.
    if (node.metadata != undefined && Array.isArray(node.metadata.widgets))
        nodeMeta.widgets = normalizeWidgets(node.metadata.widgets);

    // #662: and the lineage of a copy Duplicate selection made.
    if (node.metadata != undefined && Array.isArray(node.metadata.copiedFrom))
        nodeMeta.copiedFrom = lineageFromSpec(node.metadata.copiedFrom);

    // #662: and the node's selection tags, with the ids they held.
    if (node.metadata != undefined && Array.isArray(node.metadata.selections))
        nodeMeta.selections = normalizeSelections(node.metadata.selections);

    if (typeof node.title === "string" && node.title)
        nodeMeta.title = node.title;

    if (typeof parsedWidth === "number")
        nodeMeta.nodeWidth = parsedWidth;

    if (typeof parsedHeight === "number")
        nodeMeta.nodeHeight = parsedHeight;

    if (node.minimized === true)
        nodeMeta.minimized = true;

    if (node.dashboardPinned)
        nodeMeta.dashboardPinned = true;

    if (typeof node.dashboardX === "number") {
        nodeMeta.dashboardX = node.dashboardX;
        nodeMeta.dashboardY = node.dashboardY;
    }

    if (typeof node.dashboardWidth === "number") {
        nodeMeta.dashboardWidth = node.dashboardWidth;
        nodeMeta.dashboardHeight = node.dashboardHeight;
    }

    if (typeof node.saveOutputDataset === "boolean")
        nodeMeta.saveOutputDataset = node.saveOutputDataset;

    return nodeMeta;
}

/** A canvas node of *nodeType*, made from *options* with the canvas's own
 *  callbacks and interpreters (*runtime*). */
export function buildCodeNode(nodeType: string, options: CreateCodeNodeOptions, runtime: CodeNodeRuntime): Node {
    const {
        nodeId = uuid(),
        code = undefined,
        description = undefined,
        templateId = undefined,
        templateName = undefined,
        accessLevel = undefined,
        customTemplate = undefined,
        position = runtime.position(),
        suggestionType = "none",
        warnings = [],
        goal = "",
        inType = "DEFAULT",
        out = "DEFAULT",
        keywords = [],
        nodeWidth = undefined,
        nodeHeight = undefined,
        minimized = undefined,
        dashboardPinned = undefined,
        dashboardX = undefined,
        dashboardY = undefined,
        dashboardWidth = undefined,
        dashboardHeight = undefined,
        datasetRefs = undefined,
        appliedDatasets = undefined,
        datasetSource = undefined,
        datasetWidgets = undefined,
        modelRefs = undefined,
        saveOutputDataset = undefined,
        appearance = undefined,
        title = undefined,
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

    return {
        id: nodeId,
        type: CURIO_UNIVERSAL_NODE_TYPE,
        position,
        data: {
            nodeId: nodeId,
            pythonInterpreter: runtime.pythonInterpreter,
            jsInterpreter: runtime.jsInterpreter,
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
            minimized,
            dashboardPinned,
            dashboardX,
            dashboardY,
            dashboardWidth,
            dashboardHeight,
            datasetRefs,
            appliedDatasets,
            datasetSource,
            datasetWidgets,
            appearance,
            title,
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
                    : runtime.defaultSaveOutputDataset,
            input: "",
            inputTypes: [],
            keywords,
            outputCallback: runtime.outputCallback,
            interactionsCallback: runtime.interactionsCallback,
            propagationCallback: runtime.propagationCallback,
            ...(output !== undefined ? { output } : {}),
            ...(executedCode !== undefined ? { executedCode } : {}),
            ...(modelRefs !== undefined ? { modelRefs } : {}),
        },
    };
}

/** A canvas edge made from a Trill edge; *suggestionType* marks a suggestion's. */
export function canvasEdgeFromTrill(edge: any, suggestionType?: string): any {
    // Respect explicit handle ids in the spec (`in`, `in_1`, ... and
    // any named handle a package declares). Fall back to the
    // legacy `in_N` suffix of the edge id, then to the default "in"
    // handle, as `named_input_slot` reads them in the runner.
    let targetHandle = edge.targetHandle || "in";
    if (!edge.targetHandle) {
        const legacy = typeof edge.id === "string" ? edge.id.match(/in_(\d+)$/) : null;
        if (legacy) targetHandle = "in_" + legacy[1];
    }

    const add_edge: any = {
        id: edge.id,
        type: EdgeType.UNIDIRECTIONAL_EDGE,
        markerEnd: { type: "arrow" },
        source: edge.source,
        sourceHandle: edge.sourceHandle || "out",
        target: edge.target,
        targetHandle,
    };

    add_edge.data = {};

    if (suggestionType != undefined)
        add_edge.data.suggestionType = suggestionType;

    if (edge.metadata != undefined && edge.metadata.keywords != undefined)
        add_edge.data.keywords = edge.metadata.keywords;

    if (edge.type == "Interaction") {
        add_edge.markerStart = { type: "arrow" };
        add_edge.sourceHandle = "in/out";
        add_edge.targetHandle = "in/out";
        add_edge.type = EdgeType.BIDIRECTIONAL_EDGE;
    }

    return add_edge;
}

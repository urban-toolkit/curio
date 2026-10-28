/**
 * The canvas and the dataflow's Yjs doc, kept in step both ways.
 *
 * **One apply path.** Every change the doc takes reaches the canvas through
 * the doc's observers, whoever made it: someone else's tab, the server, this
 * tab's Ctrl+Z in an editor, this tab's typing. The observers skip only the
 * changes this tab's canvas wrote itself (`CANVAS_ORIGIN`), which the canvas
 * holds already. A node is built as a load builds it (`hook/codeNodes.ts`),
 * an edge is connected as a load connects it (`onConnect`), and a removal
 * goes through the canvas's own removal, so a change from the doc looks on
 * the canvas exactly as the same change made here.
 *
 * **The canvas to the doc.** After each commit (a layout effect, so no
 * message from the server lands between a commit and its write), the canvas
 * is serialized as a save serializes it (`TrillGenerator.generateTrill`, node
 * by node, a node that did not change keeping its last Trill), and what
 * changed since the last commit is written as one transaction
 * (`applyDataflow`): what the doc changed meanwhile stays where the change
 * leaves it alone, and nothing is written where the doc holds the value
 * already. The sections the server owns are never written from here:
 * `packages`, `datasets`, and the `timestamp` and `provenance_id` a save
 * stamps.
 *
 * **Places.** A node being dragged, here or in another tab, is written at the
 * drop: its place is one value. While someone drags, the others see the drag
 * live through awareness (`collab/presence.ts`), which writes nothing.
 *
 * **Binding.** The canvas binds once the doc's first sync is done and the
 * canvas holds the dataflow it loaded: what the doc changed since that load
 * (someone typing meanwhile) then reaches the canvas, and from then on every
 * change goes both ways. Opening a dataflow writes nothing into the doc: what
 * a load itself makes of a node (a place out of another's way, a default
 * setting) stays on the canvas until that node changes. A tab that watches
 * never writes.
 *
 * **A node removed while this tab edits its code** is taken off with a
 * message naming who removed it and **Put it back**, which adds it again with
 * this tab's code and the connections whose other end remains.
 */
import React, { useCallback, useEffect, useLayoutEffect, useRef } from "react";
import type { Edge, Node, NodeChange, ReactFlowInstance } from "reactflow";
import * as Y from "yjs";

import { TrillGenerator } from "../../TrillGenerator";
import { buildCodeNode, canvasEdgeFromTrill, nodeMetaFromTrill, type CodeNodeRuntime } from "../../hook/codeNodes";
import { pythonInterpreter, jsInterpreter } from "../../hook/useCode";
import { normalizeScenarios, type Scenario } from "../../utils/scenarios/scenarioModel";
import type { HandCategories } from "../../utils/dataflowCategories";
import { CANVAS_ORIGIN, type DocBinding } from "../collab/docContext";
import type { DataflowDocProvider } from "../collab/docProvider";
import {
    applyDataflow,
    dataflowToDoc,
    decode,
    docToDataflow,
    edgeOut,
    nodeOut,
    owned,
    same,
    CONTENT,
    EDGE_ID,
    NODE_ID,
} from "../collab/docMapping";
import { isBound } from "../collab/boundTexts";
import { editorsOf, noteRemoval, remoteDrags, removerOf, setDrag, type DragState } from "../collab/presence";
import type { SelectionEchoOptions } from "../../utils/selectionEcho";
import type { IOutput, IPropagation } from "./flowTypes";

type Fields = Record<string, any>;

/** How long a node another tab dropped waits for its place before it goes
 *  back to the doc's. */
const DROP_WAIT_MS = 2000;
/** How long a removal waits for the remover's note, to name who removed it. */
const REMOVER_WAIT_MS = 1000;
/** How often this tab's drag is told the others. */
const DRAG_EVERY_MS = 50;

/** What a node's Trill field becomes on the canvas: the node data a load
 *  builds from it (`codeNodes.ts`); `position` is the node's place. */
export const NODE_FIELD_DATA: Record<string, readonly string[]> = {
    type: ["nodeType"],
    x: ["position"],
    y: ["position"],
    width: ["nodeWidth"],
    height: ["nodeHeight"],
    minimized: ["minimized"],
    dashboardPinned: ["dashboardPinned"],
    dashboardX: ["dashboardX"],
    dashboardY: ["dashboardY"],
    dashboardWidth: ["dashboardWidth"],
    dashboardHeight: ["dashboardHeight"],
    saveOutputDataset: ["saveOutputDataset"],
    content: ["code", "defaultCode"],
    out: ["out"],
    in: ["in"],
    goal: ["goal"],
    title: ["title"],
    warnings: ["warnings"],
};

/** The same for each of a node's `metadata` settings. */
export const METADATA_FIELD_DATA: Record<string, readonly string[]> = {
    keywords: ["keywords"],
    datasetRefs: ["datasetRefs"],
    datasetSource: ["datasetSource"],
    datasetWidgets: ["datasetWidgets"],
    modelRefs: ["modelRefs"],
    appearance: ["appearance"],
    spatialJoin: ["spatialJoin"],
    simpleVis: ["simpleVis"],
    packageTemplateLabel: ["packageTemplateLabel"],
    packageTemplateConfig: ["packageTemplateConfig"],
    dataPool: ["dataPool"],
    widgets: ["widgets"],
    copiedFrom: ["copiedFrom"],
    selections: ["selections"],
};

/** The fields whose change leaves a node out of date. */
const STALE_WHEN_CHANGED = new Set(["content", "widgets", "selections", "datasetRefs", "modelRefs", "datasetSource"]);

/** The Trill fields the doc changed in one node, and the canvas data keys
 *  they touch. */
export function changedNodeData(was: Fields, now: Fields): { keys: Set<string>; trill: Set<string> } {
    const keys = new Set<string>();
    const trill = new Set<string>();
    for (const name of new Set([...Object.keys(was), ...Object.keys(now)])) {
        if (name === NODE_ID) continue;
        if (name === "metadata") {
            const before = (was.metadata ?? {}) as Fields;
            const after = (now.metadata ?? {}) as Fields;
            for (const setting of new Set([...Object.keys(before), ...Object.keys(after)])) {
                if (same(before[setting] ?? null, after[setting] ?? null)) continue;
                trill.add(setting);
                for (const key of METADATA_FIELD_DATA[setting] ?? []) keys.add(key);
            }
            continue;
        }
        if (same(was[name] ?? null, now[name] ?? null)) continue;
        trill.add(name);
        for (const key of NODE_FIELD_DATA[name] ?? []) keys.add(key);
    }
    return { keys, trill };
}

/** The Trill of one canvas node, as a save writes it. */
export function trillNodeOf(node: Node): Fields {
    return TrillGenerator.generateTrill([node], [], "").dataflow.nodes[0];
}

/** The Trill of the canvas's edges, as a save writes them. */
export function trillEdgesOf(edges: Edge[]): Fields[] {
    return TrillGenerator.generateTrill([], edges, "").dataflow.edges;
}

/** *dataflow* as the doc holds it: what a doc built from it reads back. */
export function normalizedDataflow(dataflow: Fields): Fields {
    const doc = new Y.Doc();
    try {
        dataflowToDoc(owned(dataflow), doc, "normalized");
        return docToDataflow(doc);
    } finally {
        doc.destroy();
    }
}

/** The doc's Trill, its nodes and edges by id. */
interface DocState {
    nodes: Map<string, Fields>;
    edges: Map<string, Fields>;
    fields: Fields;
}

function docStateOf(dataflow: Fields): DocState {
    const nodes = new Map<string, Fields>();
    const edges = new Map<string, Fields>();
    const fields: Fields = {};
    for (const [name, value] of Object.entries(dataflow)) {
        if (name === "nodes" && Array.isArray(value)) {
            for (const node of value) if (node && typeof node[NODE_ID] === "string") nodes.set(node[NODE_ID], node);
        } else if (name === "edges" && Array.isArray(value)) {
            for (const edge of value) if (edge && typeof edge[EDGE_ID] === "string") edges.set(edge[EDGE_ID], edge);
        } else {
            fields[name] = value;
        }
    }
    return { nodes, edges, fields };
}

/** The dataflow the canvas was built from (or saved as), and on which load. */
export interface LoadedDataflow {
    epoch: number;
    projectId: string | null;
    dataflow: Fields | null;
}

export interface DataflowDocBridge {
    /** Whether the canvas is bound to the doc. */
    bound(): boolean;
    /** Write what the canvas holds now, then wait for the server to keep this
     *  tab's every change. Whether the canvas is bound. */
    whenKept(): Promise<boolean>;
    /** This tab's drag: the others see it live. */
    noteDrag(changes: NodeChange[]): void;
    /** Who else is editing *nodeId*'s code. */
    editorsOf(nodeId: string): string[];
    /** Tell the others this tab removes *nodeIds* now. */
    noteRemoval(nodeIds: string[]): void;
}

export interface DataflowDocDeps {
    binding: DocBinding | null;
    canWrite: boolean;
    nodes: Node[];
    edges: Edge[];
    setNodes: React.Dispatch<React.SetStateAction<Node[]>>;
    setEdges: React.Dispatch<React.SetStateAction<Edge[]>>;
    reactFlow: ReactFlowInstance;
    workflowNameRef: React.MutableRefObject<string>;
    workflowGoalRef: React.MutableRefObject<string>;
    workflowDescriptionRef: React.MutableRefObject<string>;
    workflowCategoriesRef: React.MutableRefObject<HandCategories>;
    scenariosRef: React.MutableRefObject<Scenario[]>;
    autoRunRef: React.MutableRefObject<boolean>;
    /** Each changes on what the writer reads, so a commit that changes one writes it. */
    scenarios: unknown;
    workflowName: string;
    workflowGoal: string;
    workflowDescription: string;
    workflowCategories: unknown;
    autoRun: boolean;
    loadedDataflowRef: React.MutableRefObject<LoadedDataflow | null>;
    /** The dataflow fields the doc changed, set as a load sets them. */
    takeDataflowFields: (fields: Fields, nodeIds: string[]) => void;
    /** Run *apply* with nothing it does marking the dataflow Unsaved. */
    quietly: <T>(apply: () => T) => T;
    markNodeStale: (nodeId: string) => void;
    addNode: (node: Node, customWorkflowName?: string, provenance?: boolean) => void;
    onConnect: (connection: any, custom_nodes?: any, custom_edges?: any, custom_workflow?: string, provenance?: boolean, skipValidation?: boolean) => void;
    onEdgesDelete: (edges: Edge[], options?: { remote?: boolean }) => void;
    onNodesDelete: (changes: NodeChange[]) => void;
    onNodesChange: (changes: NodeChange[]) => void;
    applyNewOutput: (output: IOutput) => void;
    interactionsCallback: (interactions: any, nodeId: string) => void;
    applyNewPropagation: (propagation: IPropagation) => void;
    defaultSaveOutputDataset: boolean;
    takeCanvasPosition?: (nodeId: string, position: { x: number; y: number }) => boolean;
    setDashboardPins: React.Dispatch<React.SetStateAction<any>>;
    showToast: (message: string, variant?: any, options?: any) => void;
}

export function useDataflowDoc(deps: DataflowDocDeps): DataflowDocBridge {
    const { binding, nodes, edges, setNodes, setEdges, reactFlow, loadedDataflowRef } = deps;
    const provider = binding?.synced ? binding.provider : null;

    // The latest of everything the callbacks below read, written each render.
    const latest = useRef(deps);
    latest.current = deps;

    /** The bound provider, and the load it was bound on. */
    const boundRef = useRef<{ provider: DataflowDocProvider; epoch: number; detach: () => void } | null>(null);
    /** The canvas's Trill when the writer last ran (null: not taken yet). */
    const writerBaseRef = useRef<Fields | null>(null);
    /** The canvas's Trill right after its load, and that load's epoch. */
    const loadedCanvasRef = useRef<{ epoch: number; trill: Fields } | null>(null);
    /** The doc's Trill as the canvas last took it. */
    const docStateRef = useRef<DocState | null>(null);
    /** Each canvas node's last Trill. */
    const cacheRef = useRef(new Map<string, { node: Node; code: unknown; trill: Fields }>());
    /** Nodes another tab drags now, and those it dropped whose place is due. */
    const remoteDragRef = useRef(new Set<string>());
    const droppedRef = useRef(new Map<string, ReturnType<typeof setTimeout>>());
    const dragSentRef = useRef(0);

    const runtime = (): CodeNodeRuntime => ({
        pythonInterpreter,
        jsInterpreter,
        outputCallback: (nodeId: string, output: unknown, options?: SelectionEchoOptions) =>
            latest.current.applyNewOutput({ nodeId, output, ...options } as IOutput),
        interactionsCallback: latest.current.interactionsCallback,
        propagationCallback: latest.current.applyNewPropagation,
        defaultSaveOutputDataset: latest.current.defaultSaveOutputDataset,
        position: () => ({ x: 0, y: 0 }),
    });

    /** The canvas as a save writes it, the sections the server owns left out. */
    const canvasTrill = useCallback((): Fields => {
        const current = latest.current;
        const cache = cacheRef.current;
        const seen = new Set<string>();
        const trillNodes: Fields[] = [];
        for (const node of current.nodes) {
            seen.add(node.id);
            const cached = cache.get(node.id);
            const held = (node as any).dragging || remoteDragRef.current.has(node.id) || droppedRef.current.has(node.id);
            if (cached && (held || (cached.node === node && cached.code === node.data?.code))) {
                trillNodes.push(cached.trill);
                continue;
            }
            const trill = trillNodeOf(node);
            cache.set(node.id, { node, code: node.data?.code, trill });
            trillNodes.push(trill);
        }
        for (const id of Array.from(cache.keys())) if (!seen.has(id)) cache.delete(id);
        const dataflow: Fields = {
            nodes: trillNodes,
            edges: trillEdgesOf(current.edges),
            name: current.workflowNameRef.current,
            task: current.workflowGoalRef.current ?? "",
        };
        if (current.workflowDescriptionRef.current) dataflow.description = current.workflowDescriptionRef.current;
        dataflow.categories = current.workflowCategoriesRef.current;
        dataflow.autoRun = current.autoRunRef.current;
        dataflow.scenarios = normalizeScenarios(current.scenariosRef.current, trillNodes.map((n) => n.id));
        return dataflow;
    }, []);

    /** Write what the canvas changed since the writer last ran into the doc. */
    const write = useCallback(() => {
        const bound = boundRef.current;
        if (!bound || !latest.current.canWrite) return;
        if (latest.current.loadedDataflowRef?.current?.epoch !== bound.epoch) return;
        const target = canvasTrill();
        const base = writerBaseRef.current;
        writerBaseRef.current = target;
        if (!base) return;
        const kept = new Set((target.nodes as Fields[]).map((n) => n.id as string));
        const removed = (base.nodes as Fields[]).map((n) => n.id as string).filter((id) => !kept.has(id));
        if (removed.length) noteRemoval(bound.provider.awareness, removed);
        bound.provider.doc.transact(() => applyDataflow(bound.provider.doc, base, target), CANVAS_ORIGIN);
    }, [canvasTrill]);

    // ------------------------------------------------------------------
    // The doc to the canvas
    // ------------------------------------------------------------------

    /** Add *node* back as this tab last had it, with its connections whose
     *  other end remains. */
    const putBack = useCallback((node: Node, attached: Edge[]) => {
        const current = latest.current;
        if (current.nodes.some((n) => n.id === node.id)) return;
        const code = node.data?.code;
        const fresh = buildCodeNode(node.data?.nodeType, {
            ...nodeMetaFromTrill(trillNodeOf(node), () => node.position),
            ...(typeof code === "string" ? { code } : {}),
        }, runtime());
        current.addNode(fresh, current.workflowNameRef.current, true);
        const survivors = attached.filter((edge) => {
            const other = edge.source === node.id ? edge.target : edge.source;
            return current.nodes.some((n) => n.id === other);
        });
        if (survivors.length === 0) return;
        setNodes((prev) => {
            const all = prev.some((n) => n.id === fresh.id) ? prev : [...prev, fresh];
            const connected = [...reactFlow.getEdges()];
            for (const edge of survivors) {
                current.onConnect({ ...edge }, all, connected, current.workflowNameRef.current, true, true);
                connected.push(edge);
            }
            return prev;
        });
    }, [setNodes, reactFlow]);

    /** Someone else removed *node* while this tab was editing its code. */
    const removedWhileEditing = useCallback((node: Node, attached: Edge[]) => {
        const awareness = boundRef.current?.provider.awareness;
        const say = (who: string | null) => {
            latest.current.showToast(
                `${who ?? "Someone"} removed this node while you were editing it.`,
                "warning",
                { action: { label: "Put it back", onClick: () => putBack(node, attached) } },
            );
        };
        const named = removerOf(awareness, node.id);
        if (named || !awareness) {
            say(named);
            return;
        }
        // The note travels apart from the doc's change: wait a moment for it.
        let done = false;
        const onChange = () => {
            const who = removerOf(awareness, node.id);
            if (!who || done) return;
            done = true;
            awareness.off("change", onChange);
            say(who);
        };
        awareness.on("change", onChange);
        setTimeout(() => {
            if (done) return;
            done = true;
            awareness.off("change", onChange);
            say(null);
        }, REMOVER_WAIT_MS);
    }, [putBack]);

    /** Carry what the doc changed (*prev* to *next*) onto the canvas: every
     *  entry, or those *touched* names. */
    const applyToCanvas = useCallback((
        prev: DocState,
        next: DocState,
        touched?: { nodes: Set<string>; edges: Set<string>; fields: Set<string> },
    ) => {
        const current = latest.current;
        const held = boundRef.current?.provider;
        const doc = held?.doc;
        const awareness = held?.awareness;
        const canvasNodes = new Map(current.nodes.map((n) => [n.id, n]));
        const canvasEdges = new Map(current.edges.map((e) => [e.id, e]));
        const nodeIds = touched?.nodes ?? new Set([...prev.nodes.keys(), ...next.nodes.keys()]);
        const edgeIds = touched?.edges ?? new Set([...prev.edges.keys(), ...next.edges.keys()]);
        const fieldNames = touched?.fields ?? new Set([...Object.keys(prev.fields), ...Object.keys(next.fields)]);

        // The dataflow's own fields.
        const fields: Fields = {};
        for (const name of fieldNames) {
            if (!same(prev.fields[name] ?? null, next.fields[name] ?? null)) fields[name] = next.fields[name];
        }
        if (Object.keys(fields).length > 0) current.takeDataflowFields(fields, Array.from(next.nodes.keys()));

        // Connections that went or changed, before the nodes.
        const goneEdges: Edge[] = [];
        const newEdges: Fields[] = [];
        for (const id of edgeIds) {
            const was = prev.edges.get(id);
            const now = next.edges.get(id);
            if (was && now && same(was, now)) continue;
            const onCanvas = canvasEdges.get(id);
            const changed = !!was && !!now && !same(was, now);
            if (onCanvas && (!now || changed)) goneEdges.push(onCanvas);
            if (now && (!onCanvas || changed)) newEdges.push(now);
        }

        const removedNodes: string[] = [];
        const addedNodes: Node[] = [];
        const patches = new Map<string, { data: Fields; position?: { x: number; y: number } }>();
        for (const id of nodeIds) {
            const was = prev.nodes.get(id);
            const now = next.nodes.get(id);
            const onCanvas = canvasNodes.get(id);
            if (!now) {
                if (!onCanvas) continue;
                removedNodes.push(id);
                const editing = (awareness?.getLocalState() as { editing?: string | null } | null)?.editing;
                if (editing === id) {
                    removedWhileEditing(onCanvas, current.edges.filter((e) => e.source === id || e.target === id));
                }
                continue;
            }
            if (!onCanvas || (was && was.type !== now.type)) {
                if (onCanvas) removedNodes.push(id);
                addedNodes.push(buildCodeNode(now.type, nodeMetaFromTrill(now, () => ({ x: 0, y: 0 })), runtime()));
                continue;
            }
            if (!was || same(was, now)) continue;
            const { keys, trill } = changedNodeData(was, now);
            if (keys.size === 0) continue;
            const built = buildCodeNode(now.type, nodeMetaFromTrill(now, () => onCanvas.position), runtime());
            const data: Fields = {};
            let position: { x: number; y: number } | undefined;
            const editorHasIt = !!doc && isBound(doc, id);
            for (const key of keys) {
                if (key === "position") position = built.position;
                // Its editor took the code already, and the node takes it from there.
                else if ((key === "code" || key === "defaultCode") && editorHasIt) continue;
                else data[key] = (built.data as Fields)[key];
            }
            if (position) {
                remoteDragRef.current.delete(id);
                const due = droppedRef.current.get(id);
                if (due) clearTimeout(due);
                droppedRef.current.delete(id);
                if ((onCanvas as any).dragging || current.takeCanvasPosition?.(id, position) === true) position = undefined;
            }
            if (Object.keys(data).length > 0 || position) patches.set(id, { data, position });
            const stale = [...trill].filter((name) => STALE_WHEN_CHANGED.has(name));
            if (stale.length > 0 && !(stale.length === 1 && stale[0] === CONTENT && editorHasIt)) {
                current.markNodeStale(id);
            }
            if (trill.has("dashboardPinned")) {
                const pinned = !!now.dashboardPinned;
                current.setDashboardPins((pins: Fields) => ({ ...pins, [id]: pinned }));
            }
        }

        // What the canvas loses: connections first, as the Delete key sends them.
        const gone = new Set(removedNodes);
        for (const edge of current.edges) {
            if ((gone.has(edge.source) || gone.has(edge.target)) && !goneEdges.includes(edge)) goneEdges.push(edge);
        }
        if (goneEdges.length) {
            const ids = new Set(goneEdges.map((e) => e.id));
            current.quietly(() => current.onEdgesDelete(goneEdges, { remote: true }));
            setEdges((eds) => eds.filter((e) => !ids.has(e.id)));
        }
        if (removedNodes.length) {
            const changes = removedNodes.map((id) => ({ id, type: "remove" as const }));
            current.quietly(() => current.onNodesDelete(changes));
            current.onNodesChange(changes);
        }
        if (patches.size) {
            setNodes((nds) => nds.map((n) => {
                const patch = patches.get(n.id);
                if (!patch) return n;
                return { ...n, ...(patch.position ? { position: patch.position } : {}), data: { ...n.data, ...patch.data } };
            }));
        }
        for (const node of addedNodes) current.quietly(() => current.addNode(node, current.workflowNameRef.current, true));
        if (newEdges.length) {
            const added = addedNodes;
            setNodes((prevNodes) => {
                current.quietly(() => {
                    const all = [...prevNodes.filter((n) => !added.some((a) => a.id === n.id)), ...added];
                    const connected = [...reactFlow.getEdges()].filter((e) => !newEdges.some((n) => n.id === e.id));
                    for (const edge of newEdges) {
                        const canvasEdge = canvasEdgeFromTrill(edge);
                        current.onConnect(canvasEdge, all, connected, current.workflowNameRef.current, true, true);
                        connected.push(canvasEdge);
                    }
                });
                return prevNodes;
            });
        }
    }, [removedWhileEditing, setNodes, setEdges, reactFlow]);

    // ------------------------------------------------------------------
    // Binding
    // ------------------------------------------------------------------

    /** The doc's observers and awareness's, on *held*: what changes in the
     *  doc reaches the canvas, and so do everyone else's drags. */
    const attach = useCallback((held: DataflowDocProvider): (() => void) => {
        const doc = held.doc;
        const nodesMap = doc.getMap("nodes");
        const edgesMap = doc.getMap("edges");
        const fieldsMap = doc.getMap("dataflow");
        const scenariosMap = doc.getMap("scenarios");
        const scenarioOrder = doc.getArray("scenarioOrder");
        const touched = { nodes: new Set<string>(), edges: new Set<string>(), fields: new Set<string>() };
        let whole = false;

        const onNodes = (events: Array<Y.YEvent<any>>) => {
            for (const event of events) {
                if (event.target === nodesMap) event.changes.keys.forEach((_change, key) => touched.nodes.add(key));
                else if (event.path.length > 0) touched.nodes.add(String(event.path[0]));
            }
        };
        const onEdges = (event: Y.YMapEvent<unknown>) => {
            event.changes.keys.forEach((_change, key) => touched.edges.add(key));
        };
        const onFields = (event: Y.YMapEvent<unknown>) => {
            event.changes.keys.forEach((_change, key) => {
                if (key === "nodes" || key === "edges") whole = true;
                touched.fields.add(key);
            });
        };
        const onScenarios = () => {
            touched.fields.add("scenarios");
        };

        const onTransaction = (transaction: Y.Transaction) => {
            if (!touched.nodes.size && !touched.edges.size && !touched.fields.size && !whole) return;
            const state = docStateRef.current;
            const changed = {
                nodes: new Set(touched.nodes),
                edges: new Set(touched.edges),
                fields: new Set(touched.fields),
            };
            const wasWhole = whole;
            touched.nodes.clear();
            touched.edges.clear();
            touched.fields.clear();
            whole = false;
            if (!state || boundRef.current?.provider !== held) return;
            let next: DocState;
            if (wasWhole) {
                next = docStateOf(docToDataflow(doc));
            } else {
                next = { nodes: new Map(state.nodes), edges: new Map(state.edges), fields: { ...state.fields } };
                for (const id of changed.nodes) {
                    const node = nodesMap.get(id);
                    if (node === undefined) next.nodes.delete(id);
                    else next.nodes.set(id, nodeOut(id, node) as Fields);
                }
                for (const id of changed.edges) {
                    const edge = edgesMap.get(id);
                    if (edge === undefined) next.edges.delete(id);
                    else next.edges.set(id, edgeOut(id, edge) as Fields);
                }
                for (const name of changed.fields) {
                    if (name === "scenarios") {
                        const list = docToDataflow(doc).scenarios;
                        if (list === undefined) delete next.fields.scenarios;
                        else next.fields.scenarios = list;
                    } else if (fieldsMap.has(name)) {
                        next.fields[name] = decode(fieldsMap.get(name));
                    } else {
                        delete next.fields[name];
                    }
                }
            }
            docStateRef.current = next;
            if (transaction.origin === CANVAS_ORIGIN) return;
            applyToCanvas(state, next, wasWhole ? undefined : changed);
        };

        // Everyone else's drags, live: the node follows the pointer that drags it.
        const awareness = held.awareness;
        const onPresence = () => {
            const drags = remoteDrags(awareness);
            const before = remoteDragRef.current;
            remoteDragRef.current = new Set(drags.keys());
            for (const id of before) {
                if (drags.has(id) || droppedRef.current.has(id)) continue;
                // Dropped: its place comes with the doc's change, or the node
                // goes back to the doc's place.
                droppedRef.current.set(id, setTimeout(() => {
                    droppedRef.current.delete(id);
                    const placed = docStateRef.current?.nodes.get(id);
                    if (!placed || typeof placed.x !== "number" || typeof placed.y !== "number") return;
                    setNodes((nds) => nds.map((n) => (n.id === id && (n.position.x !== placed.x || n.position.y !== placed.y)
                        ? { ...n, position: { x: placed.x, y: placed.y } }
                        : n)));
                }, DROP_WAIT_MS));
            }
            if (drags.size === 0) return;
            setNodes((nds) => nds.map((n) => {
                const place = drags.get(n.id);
                if (!place || (n as any).dragging) return n;
                if (n.position.x === place.x && n.position.y === place.y) return n;
                return { ...n, position: { x: place.x, y: place.y } };
            }));
        };

        nodesMap.observeDeep(onNodes);
        edgesMap.observe(onEdges);
        fieldsMap.observe(onFields);
        scenariosMap.observeDeep(onScenarios);
        scenarioOrder.observe(onScenarios);
        doc.on("afterTransaction", onTransaction);
        awareness.on("change", onPresence);
        return () => {
            nodesMap.unobserveDeep(onNodes);
            edgesMap.unobserve(onEdges);
            fieldsMap.unobserve(onFields);
            scenariosMap.unobserveDeep(onScenarios);
            scenarioOrder.unobserve(onScenarios);
            doc.off("afterTransaction", onTransaction);
            awareness.off("change", onPresence);
        };
    }, [applyToCanvas, setNodes]);

    const unbind = useCallback(() => {
        boundRef.current?.detach();
        boundRef.current = null;
        docStateRef.current = null;
        writerBaseRef.current = null;
        cacheRef.current.clear();
        remoteDragRef.current.clear();
        droppedRef.current.forEach((timer) => clearTimeout(timer));
        droppedRef.current.clear();
    }, []);

    /** Bind the canvas to *held*'s doc, now synced, on the load *epoch*. */
    const bind = useCallback((held: DataflowDocProvider, epoch: number, loaded: Fields | null) => {
        const now = docStateOf(docToDataflow(held.doc));
        // What the canvas reflects: the doc it was bound to on this load (one
        // the server built anew since), else the dataflow it loaded.
        const reflected = boundRef.current?.epoch === epoch ? docStateRef.current : null;
        const previous = reflected ?? (loaded ? docStateOf(normalizedDataflow(loaded)) : now);
        unbind();
        boundRef.current = { provider: held, epoch, detach: attach(held) };
        docStateRef.current = now;
        applyToCanvas(previous, now);
        // What the canvas changed since its load, before the doc synced, goes
        // in with the next write.
        const loadedCanvas = loadedCanvasRef.current;
        writerBaseRef.current = loadedCanvas && loadedCanvas.epoch === epoch ? loadedCanvas.trill : canvasTrill();
    }, [applyToCanvas, attach, canvasTrill, unbind]);

    // Each commit: take the canvas's load, bind when due, then write what the
    // canvas changed.
    useLayoutEffect(() => {
        const loaded = loadedDataflowRef?.current ?? null;
        const epoch = loaded?.epoch ?? 0;
        // Only a canvas with a doc to bind to (not the dashboard's, nor one
        // never saved) takes its load.
        if (binding && loaded && loadedCanvasRef.current?.epoch !== epoch) {
            // The canvas holds its load once every node the load listed is on it.
            const ids = new Set(nodes.map((n) => n.id));
            const listed = (Array.isArray(loaded.dataflow?.nodes) ? loaded.dataflow!.nodes : []) as Fields[];
            if (listed.every((n) => ids.has(n?.id))) loadedCanvasRef.current = { epoch, trill: canvasTrill() };
        }
        const bound = boundRef.current;
        if (bound && (bound.epoch !== epoch || !provider || bound.provider.projectId !== loaded?.projectId)) unbind();
        if (provider && loaded && provider.projectId === loaded.projectId
            && loadedCanvasRef.current?.epoch === epoch && boundRef.current?.provider !== provider) {
            bind(provider, epoch, loaded.dataflow);
        }
        write();
    }, [nodes, edges, deps.scenarios, deps.workflowName, deps.workflowGoal, deps.workflowDescription,
        deps.workflowCategories, deps.autoRun, deps.canWrite, binding, provider, bind, unbind, write, canvasTrill,
        loadedDataflowRef]);

    useEffect(() => () => unbind(), [unbind]);

    return {
        bound: () => !!provider && boundRef.current?.provider === provider,
        whenKept: async () => {
            const held = boundRef.current?.provider;
            if (!held || held !== provider) return false;
            write();
            await held.whenKept();
            return true;
        },
        noteDrag: (changes: NodeChange[]) => {
            const held = boundRef.current?.provider;
            if (!held || !latest.current.canWrite) return;
            let dragging: DragState | null = null;
            let dropped = false;
            for (const change of changes) {
                if (change.type !== "position") continue;
                if (change.dragging && change.position) {
                    dragging = dragging ?? { nodes: {} };
                    dragging.nodes[change.id] = { x: change.position.x, y: change.position.y };
                } else if (change.dragging === false) {
                    dropped = true;
                }
            }
            if (dragging) {
                const at = Date.now();
                if (at - dragSentRef.current < DRAG_EVERY_MS) return;
                dragSentRef.current = at;
                setDrag(held.awareness, dragging);
            } else if (dropped) {
                dragSentRef.current = 0;
                setDrag(held.awareness, null);
            }
        },
        editorsOf: (nodeId: string) => editorsOf(boundRef.current?.provider.awareness, nodeId),
        noteRemoval: (nodeIds: string[]) => noteRemoval(boundRef.current?.provider.awareness, nodeIds),
    };
}

// The shapes of FlowContext and NodeActionsContext. FlowProvider.tsx creates
// both contexts and provides their values.
import type React from "react";
import type { Connection, Edge, EdgeChange, Node, NodeChange, NodeRemoveChange } from "reactflow";
import type { InstallSyncOutcome, PendingInstall } from "../../services/datasetCatalog/datasetCatalogTypes";
import type { DataflowCategories, HandCategories } from "../../utils/dataflowCategories";
import type { NotebookPane } from "../../utils/notebookLayout";
import type { NodeSettings } from "../../utils/nodeSettingsWriters";
import type { Scenario } from "../../utils/scenarios/scenarioModel";
import type { IInteraction, IOutput, IPropagation, NodeExecOutcome } from "./flowTypes";
import type { DataflowDocProvider } from "../collab/docProvider";
import type { CanvasView } from "./useNotebookView";

export interface FlowContextProps {
    nodes: Node[];
    edges: Edge[];
    outputs: IOutput[];
    setOutputs: (updateFn: (outputs: IOutput[]) => IOutput[]) => void;
    setInteractions: (updateFn: (interactions: IInteraction[]) => IInteraction[]) => void;
    /** Record a node's selection; the one callback every node's data carries. */
    interactionsCallback: (interactions: any, nodeId: string) => void;
    /** Empty the selection tags that read the view *viewId*, drawn again
     * without the selection they hold (#884): their nodes go stale. */
    clearSelectionTagsOf?: (viewId: string) => void;
    applyNewPropagation: (propagation: IPropagation) => void;
    addNode: (node: Node, customWorkflowName?: string, provenance?: boolean) => void;
    onNodesChange: (changes: NodeChange[]) => void;
    onEdgesChange: (changes: EdgeChange[]) => void;
    onConnect: (connection: Connection, custom_nodes?: any, custom_edges?: any, custom_workflow?: string, provenance?: boolean, skipValidation?: boolean, sourceAddedByLoad?: boolean) => void;
    isValidConnection: (connection: Connection) => boolean;
    /** Remove *connections* from the canvas; `remote`: the dataflow's doc
     *  removed them, and the tab that did rewrote what their removal changes. */
    onEdgesDelete: (connections: Edge[], options?: { remote?: boolean }) => void;
    onNodesDelete: (changes: NodeChange[]) => void;
    setPinForDashboard: (nodeId: string, value: boolean) => void;
    /** True while the tree is rendering the dashboard page rather than the canvas. */
    dashboardOn: boolean;
    dashboardLocked: boolean;
    /** Does a pinned tile, or a scenario's context or outcomes (#662), need
     * this node's output saved? */
    isDashboardSource: (nodeId: string) => boolean;
    setDashboardLocked: React.Dispatch<React.SetStateAction<boolean>>;
    applyNewOutput: (output: IOutput) => void;
    hydrateRestoredOutputs: (outputs: IOutput[], edges?: readonly any[]) => void;

    // NEW CODE
    dashboardPins: { [key: string]: boolean };
    workflowNameRef: React.MutableRefObject<string>;
    setWorkflowName: (name: string) => void;
    workflowDescriptionRef: React.MutableRefObject<string>;
    workflowDescription: string;
    setWorkflowDescription: (description: string) => void;
    allMinimized: number;
    setAllMinimized: (value: number) => void;
    expandStatus: 'expanded' | 'minimized';
    setExpandStatus: (value: 'expanded' | 'minimized') => void;
    suggestionsLeft: number;
    workflowGoal: string;
    setWorkflowGoal: (goal: string) => void;
    loading: boolean;

    applyRemoveChanges: (changes: NodeRemoveChange[]) => void;
    // Reviewed plan removals (dev/62): victims + their edge cascade leave in
    // one operation, without the manual "remove the edges first" guard.
    applyReviewedRemovals: (nodeIds: string[], edgeIds: string[]) => void;
    loadParsedTrill: (workflowName: string, task: string, node: any, edges: any, provenance?: boolean, merge?: boolean, packages?: string[], description?: string, datasets?: any[], categories?: HandCategories, scenarios?: unknown, fit?: boolean, autoRun?: boolean) => void;
    packages: string[];
    setPackages: (pkgs: string[]) => void;
    addPackage: (pkg: string) => void;
    removePackage: (pkg: string) => void;
    dataflowDatasets: any[];
    setDataflowDatasets: React.Dispatch<React.SetStateAction<any[]>>;
    pendingInstalls: PendingInstall[];
    beginPendingInstall: (entry: Omit<PendingInstall, "startedAt">) => void;
    endPendingInstall: (key: string) => void;
    failPendingInstall: (key: string) => void;
    updateDataNode: (nodeId: string, newData: any) => void;
    updateWarnings: (trill_spec: any) => void;
    updateDefaultCode: (nodeId: string, content: string) => void;
    /** Set one node's content for BOTH the editor (``defaultCode``) and the
     * serializer (``code``) through provider state — the agent apply→canvas
     * bridge's content path (dev/51; RF-store writes get clobbered by the
     * controlled re-sync). Merges into ``data``, never replaces it. A node
     * whose code is its state takes it through its own writer
     * (``utils/nodeCodeWriters``), its change named after *author*, the
     * agent that wrote it. */
    applyNodeContent: (nodeId: string, content: string, author?: string) => void;
    /** Change one node's settings, as the agent bridge applies a reviewed
     * change: each through the setter the node registered for it, as a pick
     * in the node makes it, the rest into its data through ``updateDataNode``
     * (``utils/nodeSettingsWriters``). Files no Provenance entry. */
    applyNodeSettings: (nodeId: string, settings: NodeSettings) => void;
    updateSubtasks: (trill: any) => void;
    cleanCanvas: () => void;
    flagBasedOnKeyword: (keywordIndex?: number) => void;
    eraseWorkflowSuggestions: () => void;
    acceptSuggestion: (nodeId: string) => void;
    updateKeywords: (trill: any) => void;

    // Project state
    projectId: string | null;
    projectName: string;
    /** A canvas bound to no doc holds changes no one keeps: a dataflow not
     *  saved yet, a hosted guest's own canvas, the dashboard's layout. */
    projectDirty: boolean;
    projectSavedAt: Date | null;
    /** The dataflow's doc the canvas is bound to, or null: what the top bar's
     *  Saved, Saving... or Offline reads (`useSaveState`). */
    boundDoc: DataflowDocProvider | null;
    /** Resolves true once no change this tab made waits for the server (at
     *  once on a canvas bound to no doc), false when it could not reach the
     *  server in time. */
    whenChangesKept: () => Promise<boolean>;
    nodeExecStatus: Record<string, "stale" | "executed" | "errored">;
    viewerMode: "owner" | "shared";

    /** The hand-set categories, saved with the dataflow. */
    workflowCategories: HandCategories;
    /** Source and automatic categories, from the last load or save. */
    serverCategories: DataflowCategories;
    /** The dataflow's scenarios (#662), saved with it. A member's id names a
     * node the canvas may no longer hold until the list is written again. */
    scenarios: Scenario[];
    /** "Run stale nodes automatically" (#845), saved with the dataflow; off by default. */
    autoRun: boolean;

    // Project operations
    /** Rename the open dataflow, writing BOTH name stores (#230). False if blank. */
    renameDataflow: (name: string) => boolean;
    /** Replace the hand-set categories. */
    updateDataflowCategories: (next: HandCategories) => void;
    /** Replace the scenarios; the outputs they read are saved a moment later. */
    setScenarios: (next: Scenario[]) => void;
    /** Turn auto-run on or off. */
    setAutoRun: (on: boolean) => void;
    /** File > Save: makes a dataflow not saved yet, and gives a saved one a
     * version named Saved once the server holds every change. Rejects with
     * the reason it could not. */
    saveDataflow: () => Promise<{ id: string; created: boolean }>;
    /** The dashboard's Save layout: each tile's place and size, and nothing else. */
    saveDashboardLayout: () => Promise<void>;
    saveAsNewProject: (name: string, copyOf?: string | null) => Promise<any>;
    /** The dataflow's id for an action on the server's copy of it, once the
     * server holds every change; a dataflow not saved yet is made first. */
    ensureProjectId: () => Promise<string | null>;
    /** Record the outputs the canvas holds that the dataflow records. */
    recordOutputs: (nodeIds?: readonly string[]) => Promise<InstallSyncOutcome>;
    /** The same, a moment from now: after a pin, a scenario or a node's Save
     *  output switched (`useDashboardPinSave`). */
    recordOutputsSoon?: () => void;
    /** Open the owner's dataflow; with `lastResults`, with the results its canvas was left with. */
    loadProject: (id: string, options?: { lastResults?: boolean }) => Promise<any>;
    loadSharedProject: (id: string) => Promise<any>;
    discardProject: () => void;
    markDirty: () => void;
    markNodeExecuted: (nodeId: string) => void;
    markNodeStale: (nodeId: string) => void;
    markNodeErrored: (nodeId: string) => void;
    playAllNodes: () => void;
    /** Run *target*, or every node of a list (a scenario's levers, #662), and
     * the ancestors whose output cannot be reused. */
    playNodesUpTo: (target: string | readonly string[]) => void;
    signalNodeExecDone: (nodeId: string, outcome?: NodeExecOutcome) => void;
    /**
     * The browser is walking a run (Run All, run-up-to, or the nodes a run on
     * the server left to a tab). State, not a ref, so buttons can show it (#271).
     */
    isRunActive: boolean;
    /**
     * A run on the server is saving, starting or going. Apart from isRunActive
     * so a chart still draws as its data arrives; a control that means "a run
     * is going" reads both.
     */
    serverRunActive: boolean;
    /**
     * On a dashboard, why the last viewer's run stopped before the tiles: a
     * step this browser could not run (useDashboardRun). Null otherwise.
     */
    dashboardStopped: string | null;
    /** Stop the run in flight: clears the guard so the next play is accepted. */
    cancelRun: () => void;
    /** Follow a just-opened dataflow's last run on the server if it goes, and offer to finish one that waits for a tab. */
    attachLatestRun: (projectId: string) => Promise<void>;
    /** Auto-run is offered: Run All runs on the server here (#845). */
    autoRunAvailable: boolean;
    /** A widget value changed what *nodeIds* compute: with auto-run on, they and the nodes
     * below them run once the changes settle (#845). */
    requestAutoRun: (nodeIds: readonly string[]) => void;
    /** Run *nodeIds* and every node below them now, the nodes an automatic run takes
     * (`autoRunTargets`), whether auto-run is on or not: the Map Editor node's Commit edits. */
    runDownstream?: (nodeIds: readonly string[]) => void;
    /** A dashboard opened (#1117): what its nodes are saved with is kept, and a tile with
     * no saved output runs the nodes before it. Only on a dashboard. */
    dashboardOpened?: (projectId: string) => void;
    defaultSaveOutputDataset: boolean;
    setDefaultSaveOutputDataset: (value: boolean) => void;

    /** How the dataflow is shown: the canvas, or a column of notebook cells (`?view=notebook`). */
    canvasView: CanvasView;
    setCanvasView: (view: CanvasView) => void;
    notebookOn: boolean;
    /** How tall the notebook's column is, so the page can scroll all of it. */
    notebookContentHeight: number;
    setNotebookPane: (pane: NotebookPane) => void;
    registerNotebookScroller: (element: HTMLElement | null) => void;
    /** In the notebook view, scroll the first of these nodes' cells into view
     *  (with `ifMoved`, only if the change under way moves it); false on the canvas. */
    revealNodes: (nodeIds: string[], options?: { ifMoved?: boolean }) => boolean;

    /** Note the dataflow the canvas holds now, as a load or a create leaves
     *  it, for the canvas's binding to the dataflow's doc (`useDataflowDoc`). */
    noteLoadedDataflow?: (dataflow: any, projectId?: string | null) => void;
    /** The canvas's binding to the dataflow's doc. */
    dataflowDoc?: {
        /** Whether the canvas is bound to the doc. */
        bound(): boolean;
        /** This tab's drag, which the others see live. */
        noteDrag(changes: NodeChange[]): void;
        /** Who else is editing a node's code. */
        editorsOf(nodeId: string): string[];
        /** Tell the others this tab removes these nodes now. */
        noteRemoval(nodeIds: string[]): void;
        /** Run *proceed*, which removes *nodeIds*, once asked if anyone
         *  else is editing one of them. */
        askBeforeRemoving(nodeIds: readonly string[], proceed: () => void): void;
        /** A node's data changed in place, with no new node (a widget's
         *  value, a selection tag): the doc takes it now. */
        noteNodeData(nodeId: string): void;
    };
}

// Stable context for NodeContainer — only updates when goal/minimized change, NOT on node drag
export interface NodeActionsContextProps {
    workflowNameRef: React.MutableRefObject<string>;
    workflowName: string;
    applyRemoveChanges: (changes: any[]) => void;
    setPinForDashboard: (nodeId: string, value: boolean) => void;
    allMinimized: number;
    setAllMinimized: (value: number) => void;
    expandStatus: 'expanded' | 'minimized';
    setExpandStatus: (value: 'expanded' | 'minimized') => void;
    updateDataNode: (nodeId: string, newData: any) => void;
    updateDefaultCode: (nodeId: string, content: string) => void;
    workflowGoal: string;
    acceptSuggestion: (nodeId: string) => void;
    setWorkflowName: (name: string) => void;
}

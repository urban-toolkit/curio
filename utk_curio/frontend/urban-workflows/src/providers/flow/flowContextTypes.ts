// The shapes of FlowContext and NodeActionsContext. FlowProvider.tsx creates
// both contexts and provides their values.
import type React from "react";
import type { Connection, Edge, EdgeChange, Node, NodeChange, NodeRemoveChange } from "reactflow";
import type { InstallSyncOutcome, PendingInstall } from "../../services/datasetCatalog/datasetCatalogTypes";
import type { DataflowCategories, HandCategories } from "../../utils/dataflowCategories";
import type { NotebookPane } from "../../utils/notebookLayout";
import type { Scenario } from "../../utils/scenarios/scenarioModel";
import type { IInteraction, IOutput, IPropagation, NodeExecOutcome } from "./flowTypes";
import type { CanvasView } from "./useNotebookView";

export interface FlowContextProps {
    nodes: Node[];
    edges: Edge[];
    outputs: IOutput[];
    setOutputs: (updateFn: (outputs: IOutput[]) => IOutput[]) => void;
    setInteractions: (updateFn: (interactions: IInteraction[]) => IInteraction[]) => void;
    /** Record a node's selection; the one callback every node's data carries. */
    interactionsCallback: (interactions: any, nodeId: string) => void;
    applyNewPropagation: (propagation: IPropagation) => void;
    addNode: (node: Node, customWorkflowName?: string, provenance?: boolean) => void;
    onNodesChange: (changes: NodeChange[]) => void;
    onEdgesChange: (changes: EdgeChange[]) => void;
    onConnect: (connection: Connection, custom_nodes?: any, custom_edges?: any, custom_workflow?: string, provenance?: boolean, skipValidation?: boolean, sourceAddedByLoad?: boolean) => void;
    isValidConnection: (connection: Connection) => boolean;
    onEdgesDelete: (connections: Edge[]) => void;
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
    loadParsedTrill: (workflowName: string, task: string, node: any, edges: any, provenance?: boolean, merge?: boolean, packages?: string[], description?: string, datasets?: any[], categories?: HandCategories, scenarios?: unknown, fit?: boolean) => void;
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
     * controlled re-sync). Merges into ``data``, never replaces it. */
    applyNodeContent: (nodeId: string, content: string) => void;
    updateSubtasks: (trill: any) => void;
    cleanCanvas: () => void;
    flagBasedOnKeyword: (keywordIndex?: number) => void;
    eraseWorkflowSuggestions: () => void;
    acceptSuggestion: (nodeId: string) => void;
    updateKeywords: (trill: any) => void;

    // Project state
    projectId: string | null;
    projectName: string;
    projectDirty: boolean;
    projectSavedAt: Date | null;
    nodeExecStatus: Record<string, "stale" | "executed" | "errored">;
    viewerMode: "owner" | "shared";

    /** The hand-set categories, saved with the dataflow. */
    workflowCategories: HandCategories;
    /** Source and automatic categories, from the last load or save. */
    serverCategories: DataflowCategories;
    /** The dataflow's scenarios (#662), saved with it. Member ids of nodes
     * deleted since the last save are dropped when it saves. */
    scenarios: Scenario[];

    // Project operations
    /** Rename the open dataflow, writing BOTH name stores (#230). False if blank. */
    renameDataflow: (name: string) => boolean;
    /** Replace the hand-set categories; the dataflow is dirty until the next save. */
    updateDataflowCategories: (next: HandCategories) => void;
    /** Replace the scenarios; the dataflow is dirty until the next save. */
    setScenarios: (next: Scenario[]) => void;
    saveCurrentProject: (nameOverride?: string, options?: { omitOutputs?: boolean }) => Promise<any>;
    saveAsNewProject: (name: string) => Promise<any>;
    ensureProjectId: () => Promise<string | null>;
    persistDataflowForInstall: (nodeIds?: readonly string[]) => Promise<InstallSyncOutcome>;
    loadProject: (id: string) => Promise<any>;
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
    /** Stop the run in flight: clears the guard so the next play is accepted. */
    cancelRun: () => void;
    /** Show the outputs of a just-opened dataflow's last run on the server, and follow it if it goes. */
    attachLatestRun: (projectId: string, restored: ReadonlySet<string>) => Promise<void>;
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

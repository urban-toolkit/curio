import { useCallback, useMemo } from "react";
import { useReactFlow } from "reactflow";
import { v4 as uuid } from "uuid";

import { useFlowContext } from "../../providers/FlowProvider";
import { useToastContext } from "../../providers/ToastProvider";
import { useCode } from "../../hook/useCode";
import { TrillGenerator } from "../../TrillGenerator";
import { isDrawnHidden } from "../../utils/hiddenNodes";
import type { Scenario, SharedKind } from "../../utils/scenarios/scenarioModel";
import { updateSharedLook } from "../../utils/scenarios/scenarioSets";
import { duplicateSelection } from "../../utils/scenarios/duplicateSelection";
import {
  createScenario,
  deleteScenario,
  nextScenarioColor,
  nextScenarioName,
  updateScenario,
  type ScenarioEdit,
} from "../../utils/scenarios/scenarioEdits";
import { liveScenarios, scenarioParts } from "../../utils/scenarios/scenarioParts";
// The context's own module, not the provider's: the provider mounts the
// drawer, whose In project tab runs these commands.
import { useScenarioCatalogDrawer } from "../../providers/scenarioCatalog/scenarioCatalogDrawerContext";
import { scenarioBoxHeight } from "./ScenarioLayers";
import { useScenarioUi } from "./scenarioUi";

/** Room left between a selection and its duplicate, below it. */
const DUPLICATE_GAP = 80;

/**
 * The canvas's scenario commands (#662): saving a selection or the whole
 * dataflow as a scenario, Duplicate selection, Run scenario, collapse and
 * expand, and the edits of the Scenario Catalog drawer's In project tab. Every
 * change goes through the flow's `setScenarios`, so the dataflow is dirty until
 * its next save. A command that makes a scenario opens that tab, where the new
 * scenario is listed.
 */
export function useScenarioActions() {
  const {
    scenarios: saved,
    scenarioSets,
    nodes,
    setScenarios,
    playNodesUpTo,
    markDirty,
    workflowNameRef,
    workflowGoal,
  } = useFlowContext();
  // Every edit reads, and writes, the members still on the canvas: the list
  // keeps a deleted node until the next save.
  const scenarios = useMemo(() => liveScenarios(saved, nodes), [saved, nodes]);
  const { loadTrill } = useCode();
  const reactFlow = useReactFlow();
  const { showToast } = useToastContext();
  const { openScenarioCatalogDrawer, closeScenarioCatalogDrawer } = useScenarioCatalogDrawer();
  const { setDefine } = useScenarioUi();
  const showInProject = useCallback(
    () => openScenarioCatalogDrawer({ tab: "installed" }),
    [openScenarioCatalogDrawer],
  );

  const selectedIds = useCallback(
    () => reactFlow.getNodes().filter((n) => n.selected && !isDrawnHidden(n)).map((n) => n.id),
    [reactFlow],
  );

  const apply = useCallback(
    (edit: ScenarioEdit, done?: string) => {
      if (edit.error !== undefined) {
        showToast(edit.error, "warning");
        return false;
      }
      setScenarios(edit.scenarios);
      if (done) showToast(done, "success");
      return true;
    },
    [setScenarios, showToast],
  );

  /**
   * Define scenario: opens the define panel beside the canvas, which asks for
   * the nodes unique to the scenario, then has its context and outcomes
   * confirmed and its set chosen; nothing is saved until its Save. Nodes
   * selected already, and in no scenario, are its first selection.
   */
  const saveSelectionAsScenario = useCallback(() => {
    const boxed = new Set(scenarios.flatMap((s) => s.nodes));
    const ids = [...new Set(selectedIds())].filter((id) => !boxed.has(id));
    closeScenarioCatalogDrawer();
    setDefine({ mode: "new", nodes: ids });
  }, [scenarios, selectedIds, closeScenarioCatalogDrawer, setDefine]);

  /**
   * Edit scenario: opens the define panel on a saved scenario, where its nodes,
   * shared context and outcomes, name, color and set are changed. A collapsed
   * scenario is expanded, so its nodes can be seen and selected.
   */
  const editScenario = useCallback(
    (id: string) => {
      const scenario = scenarios.find((s) => s.id === id);
      if (!scenario) return;
      closeScenarioCatalogDrawer();
      if (scenario.collapsed) setScenarios(updateScenario(scenarios, id, { collapsed: false }));
      setDefine({ mode: "edit", scenarioId: id });
    },
    [scenarios, closeScenarioCatalogDrawer, setScenarios, setDefine],
  );

  const saveDataflowAsScenario = useCallback(() => {
    const all = reactFlow.getNodes().map((n) => n.id);
    if (all.length === 0) {
      showToast("The dataflow has no nodes to save as a scenario.", "warning");
      return;
    }
    const edit = createScenario(scenarios, all, { id: uuid() });
    if (apply(edit, edit.scenarios ? `Saved the dataflow as "${edit.scenarios.at(-1)!.name}".` : undefined)) {
      showInProject();
    }
  }, [reactFlow, scenarios, apply, showToast, showInProject]);

  /** Copy *ids* below them, with the edges between them, and wire every edge
   *  entering them into the copy too; the copy's ids by original id. */
  const copyBelow = useCallback(
    (ids: readonly string[]) => {
      const chosen = new Set(ids);
      const nodes = reactFlow.getNodes();
      const picked = nodes.filter((n) => chosen.has(n.id));
      const top = Math.min(...picked.map((n) => n.position.y));
      const bottom = Math.max(...picked.map((n) => n.position.y + (n.height ?? 0)));
      const spec = TrillGenerator.generateTrill(nodes, reactFlow.getEdges(), workflowNameRef.current, workflowGoal);
      const copy = duplicateSelection(spec.dataflow, ids, {
        newId: uuid,
        offset: { x: 0, y: bottom - top + DUPLICATE_GAP },
      });
      // Built by the loader every dataflow goes through, merged into the
      // canvas as ordinary nodes ("none" is a node that is not a suggestion).
      loadTrill({ dataflow: { ...spec.dataflow, nodes: copy.nodes, edges: copy.edges } }, "none");
      markDirty();
      return copy.ids;
    },
    [reactFlow, workflowNameRef, workflowGoal, loadTrill, markDirty],
  );

  /** Duplicate selection: the selected nodes, copied below them. */
  const duplicate = useCallback(() => {
    const ids = selectedIds();
    if (ids.length === 0) {
      showToast("Select the nodes to duplicate first (Shift and drag).", "warning");
      return;
    }
    copyBelow(ids);
    showToast(`Duplicated ${ids.length} node${ids.length === 1 ? "" : "s"}.`, "success");
  }, [selectedIds, copyBelow, showToast]);

  /**
   * Duplicate scenario: its own nodes copied below them, made a scenario of
   * the same set with the next color and the same shared context, which the
   * define panel then opens on, at Name & set, to be
   * named, recolored or put in another set. A collapsed scenario stays
   * collapsed, and so does its copy, its box just below the original's.
   * The copy reads what the original reads but feeds nothing (its outputs
   * are left unwired), so it has no shared outcomes until they are wired and
   * added.
   */
  const duplicateScenario = useCallback(
    (id: string) => {
      const scenario = scenarios.find((s) => s.id === id);
      if (!scenario || scenario.nodes.length === 0) return;
      let box: { x: number; y: number } | undefined;
      if (scenario.collapsed) {
        const members = reactFlow.getNodes().filter((n) => scenario.nodes.includes(n.id));
        const at = scenario.box ?? {
          x: Math.min(...members.map((n) => n.position.x)),
          y: Math.min(...members.map((n) => n.position.y)),
        };
        box = { x: at.x, y: at.y + scenarioBoxHeight(scenario.nodes) + DUPLICATE_GAP };
      }
      const ids = copyBelow(scenario.nodes);
      const twin: Scenario = {
        id: uuid(),
        name: nextScenarioName(scenarios),
        color: nextScenarioColor(scenarios),
        nodes: scenario.nodes.map((n) => ids.get(n)).filter((n): n is string => Boolean(n)),
        ...(scenario.set ? { set: scenario.set } : {}),
        ...(scenario.context ? { context: [...scenario.context] } : {}),
        outcomes: [],
        ...(box ? { collapsed: true, box } : {}),
      };
      setScenarios([...scenarios, twin]);
      closeScenarioCatalogDrawer();
      setDefine({ mode: "edit", scenarioId: twin.id, step: 3 });
    },
    [scenarios, reactFlow, copyBelow, setScenarios, closeScenarioCatalogDrawer, setDefine],
  );

  /** Run the scenario's levers, and only those of its context nodes that cannot be reused. */
  const runScenario = useCallback(
    (id: string) => {
      const scenario = scenarios.find((s) => s.id === id);
      if (!scenario) return;
      const { levers } = scenarioParts(scenario, reactFlow.getNodes(), reactFlow.getEdges());
      if (levers.length === 0) {
        showToast(`"${scenario.name}" has no nodes to run.`, "warning");
        return;
      }
      playNodesUpTo(levers);
    },
    [scenarios, reactFlow, playNodesUpTo, showToast],
  );

  const update = useCallback(
    (id: string, patch: Parameters<typeof updateScenario>[2]) => setScenarios(updateScenario(scenarios, id, patch)),
    [scenarios, setScenarios],
  );

  const setCollapsed = useCallback((id: string, collapsed: boolean) => update(id, { collapsed }), [update]);

  const moveBox = useCallback((id: string, box: { x: number; y: number }) => update(id, { box }), [update]);

  /** Collapse or expand the shared context or shared outcomes of the set *setId*. */
  const setSharedCollapsed = useCallback(
    (setId: string, kind: SharedKind, collapsed: boolean) =>
      setScenarios(saved, updateSharedLook(scenarioSets ?? [], setId, kind, { collapsed })),
    [saved, scenarioSets, setScenarios],
  );

  const moveSharedBox = useCallback(
    (setId: string, kind: SharedKind, box: { x: number; y: number }) =>
      setScenarios(saved, updateSharedLook(scenarioSets ?? [], setId, kind, { box })),
    [saved, scenarioSets, setScenarios],
  );

  /** Rename the scenario set *id*; a name another set has is refused by the caller. */
  const renameSet = useCallback(
    (id: string, name: string) =>
      setScenarios(saved, (scenarioSets ?? []).map((s) => (s.id === id ? { ...s, name } : s))),
    [saved, scenarioSets, setScenarios],
  );

  const remove = useCallback((id: string) => setScenarios(deleteScenario(scenarios, id)), [scenarios, setScenarios]);

  return {
    saveSelectionAsScenario,
    editScenario,
    saveDataflowAsScenario,
    duplicate,
    duplicateScenario,
    runScenario,
    update,
    setCollapsed,
    moveBox,
    setSharedCollapsed,
    moveSharedBox,
    renameSet,
    remove,
  };
}

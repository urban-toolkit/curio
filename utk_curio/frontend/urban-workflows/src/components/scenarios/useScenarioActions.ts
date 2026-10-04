import { useCallback } from "react";
import { useReactFlow } from "reactflow";
import { v4 as uuid } from "uuid";

import { useFlowContext } from "../../providers/FlowProvider";
import { useToastContext } from "../../providers/ToastProvider";
import { useCode } from "../../hook/useCode";
import { TrillGenerator } from "../../TrillGenerator";
import { isDrawnHidden } from "../../utils/hiddenNodes";
import type { Scenario } from "../../utils/scenarios/scenarioModel";
import { duplicateSelection } from "../../utils/scenarios/duplicateSelection";
import {
  addNodesToScenario,
  createScenario,
  deleteScenario,
  nextScenarioColor,
  nextScenarioName,
  overlapProblem,
  removeNodesFromScenarios,
  updateScenario,
  type ScenarioEdit,
} from "../../utils/scenarios/scenarioEdits";
import { scenarioParts } from "../../utils/scenarios/scenarioParts";
import { useScenarioUi } from "./scenarioUi";

/** Room left between a selection and its duplicate, below it. */
const DUPLICATE_GAP = 80;

/**
 * The canvas's scenario commands (#662): saving a selection or the whole
 * dataflow as a scenario, Duplicate selection, Run scenario, collapse and
 * expand, and the panel's edits. Every change goes through the flow's
 * `setScenarios`, so the dataflow is dirty until its next save.
 */
export function useScenarioActions() {
  const { scenarios, setScenarios, playNodesUpTo, markDirty, workflowNameRef, workflowGoal } = useFlowContext();
  const { loadTrill } = useCode();
  const reactFlow = useReactFlow();
  const { showToast } = useToastContext();
  const { setPanelOpen } = useScenarioUi();

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

  const saveSelectionAsScenario = useCallback(() => {
    const edit = createScenario(scenarios, selectedIds(), { id: uuid() });
    if (apply(edit, edit.scenarios ? `Saved the selection as "${edit.scenarios.at(-1)!.name}".` : undefined)) {
      setPanelOpen(true);
    }
  }, [scenarios, selectedIds, apply, setPanelOpen]);

  const saveDataflowAsScenario = useCallback(() => {
    const all = reactFlow.getNodes().map((n) => n.id);
    if (all.length === 0) {
      showToast("The dataflow has no nodes to save as a scenario.", "warning");
      return;
    }
    const edit = createScenario(scenarios, all, { id: uuid() });
    if (apply(edit, edit.scenarios ? `Saved the dataflow as "${edit.scenarios.at(-1)!.name}".` : undefined)) {
      setPanelOpen(true);
    }
  }, [reactFlow, scenarios, apply, showToast, setPanelOpen]);

  /**
   * Copy the selected nodes below them, with the edges between them, and wire
   * every edge entering the selection into the copy too. *asScenario* makes the
   * selection a scenario (unless it is one) and the copy another.
   */
  const duplicate = useCallback(
    (asScenario: boolean) => {
      const ids = selectedIds();
      if (ids.length === 0) {
        showToast("Select the nodes to duplicate first (Shift and drag).", "warning");
        return;
      }
      const chosen = new Set(ids);
      const already = scenarios.find(
        (s) => s.nodes.length === ids.length && s.nodes.every((id) => chosen.has(id)),
      );
      if (asScenario && !already) {
        const problem = overlapProblem(scenarios, ids);
        if (problem) {
          showToast(problem, "warning");
          return;
        }
      }

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

      if (!asScenario) {
        showToast(`Duplicated ${ids.length} node${ids.length === 1 ? "" : "s"}.`, "success");
        return;
      }
      let next: Scenario[] = scenarios;
      if (!already) {
        next = [...next, { id: uuid(), name: nextScenarioName(next), color: nextScenarioColor(next), nodes: ids }];
      }
      const twin: Scenario = {
        id: uuid(),
        name: nextScenarioName(next),
        color: nextScenarioColor(next),
        nodes: [...copy.ids.values()],
      };
      setScenarios([...next, twin]);
      setPanelOpen(true);
      showToast(`Duplicated the selection as "${twin.name}".`, "success");
    },
    [selectedIds, scenarios, reactFlow, workflowNameRef, workflowGoal, loadTrill, markDirty, showToast, setScenarios, setPanelOpen],
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

  const addSelected = useCallback(
    (id: string) => apply(addNodesToScenario(scenarios, id, selectedIds())),
    [scenarios, selectedIds, apply],
  );

  /** Take the selected nodes of the scenario *id* out of it; it keeps the others. */
  const removeSelected = useCallback(
    (id: string) => {
      const scenario = scenarios.find((s) => s.id === id);
      if (!scenario) return;
      const ids = selectedIds().filter((n) => scenario.nodes.includes(n));
      if (ids.length === 0) {
        showToast(`Select nodes of "${scenario.name}" to take out first.`, "warning");
        return;
      }
      setScenarios(removeNodesFromScenarios(scenarios, ids));
    },
    [scenarios, selectedIds, setScenarios, showToast],
  );

  const remove = useCallback((id: string) => setScenarios(deleteScenario(scenarios, id)), [scenarios, setScenarios]);

  return {
    saveSelectionAsScenario,
    saveDataflowAsScenario,
    duplicate,
    runScenario,
    update,
    setCollapsed,
    moveBox,
    addSelected,
    removeSelected,
    remove,
  };
}

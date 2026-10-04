import { useCallback, useMemo } from "react";
import { useReactFlow } from "reactflow";
import { v4 as uuid } from "uuid";

import { useCode } from "../../hook/useCode";
import { useFlowContext } from "../../providers/FlowProvider";
import { useToastContext } from "../../providers/ToastProvider";
import { refreshPackageRegistry } from "../../registry/packageRegistryBootstrap";
import { setCurrentProjectPackages } from "../../registry/projectPackagesStore";
import { buildDatasetLoaderNodeOptions } from "../../services/datasetCatalog";
import { scenarioCatalogApi, type ScenarioDragPayload } from "../../services/scenarioCatalog";
import { TrillGenerator } from "../../TrillGenerator";
import { restoredByNode, restoredOutputs, withOutputs } from "../../utils/restoredOutputs";
import { dropGraph, loaderNodes, planScenarioDrop } from "../../utils/scenarios/scenarioDrop";
import { liveScenarios } from "../../utils/scenarios/scenarioParts";

/**
 * A scenario dragged from the Scenario Catalog onto this canvas (#662).
 *
 * The server says what the drop copies and whether it can (a package that
 * cannot be added, a context with no saved output); the canvas picks the
 * copies' ids (`planScenarioDrop`); the server then adds the packages and
 * copies the saved outputs to those ids; and the canvas loads the copies the
 * way Duplicate selection does, with the copied outputs restored the way
 * opening a project restores them, and adds the scenario collapsed.
 */
export function useScenarioDrop() {
  const {
    scenarios: saved,
    nodes,
    setScenarios,
    setOutputs,
    hydrateRestoredOutputs,
    markDirty,
    ensureProjectId,
    workflowNameRef,
    workflowGoal,
  } = useFlowContext();
  const scenarios = useMemo(() => liveScenarios(saved, nodes), [saved, nodes]);
  const { loadTrill } = useCode();
  const reactFlow = useReactFlow();
  const { showToast } = useToastContext();

  return useCallback(
    async (payload: ScenarioDragPayload, at: { x: number; y: number }) => {
      const target = await ensureProjectId();
      if (!target) {
        showToast("Save this dataflow first, then drag the scenario again.", "warning");
        return;
      }
      try {
        const plan = await scenarioCatalogApi.getCopyPlan(payload.projectId, payload.scenarioId, target);
        if (plan.problems.length > 0) {
          showToast(plan.problems.join(" "), "error");
          return;
        }
        const live = TrillGenerator.generateTrill(
          reactFlow.getNodes(), reactFlow.getEdges(), workflowNameRef.current, workflowGoal,
        );
        const drop = planScenarioDrop(plan, live.dataflow, scenarios, { newId: uuid, at });
        if ("error" in drop) {
          showToast(drop.error, "warning");
          return;
        }
        const copied = await scenarioCatalogApi.copyInto(payload.projectId, payload.scenarioId, target, drop.outputs);
        if (copied.added.length > 0) {
          // As the Node Catalog's Add does, and before the nodes that use them
          // are built, so none of them comes up as an unknown kind.
          setCurrentProjectPackages(copied.packages);
          await refreshPackageRegistry();
        }
        const graph = dropGraph(drop, loaderNodes(drop.loaders, copied.datasets, buildDatasetLoaderNodeOptions));
        const loaded = loadTrill(
          { dataflow: { ...live.dataflow, nodes: graph.nodes, edges: graph.edges } },
          "none",
          undefined,
          restoredByNode(copied.outputs),
        );
        if (copied.outputs.length > 0) {
          const outputs = restoredOutputs(copied.outputs);
          setOutputs((prev) => withOutputs(prev, outputs));
          hydrateRestoredOutputs(outputs, loaded.edges);
        }
        setScenarios([...scenarios, drop.scenario]);
        markDirty();
        const added = copied.added.length > 0 ? ` Added ${copied.added.join(", ")} to this project.` : "";
        showToast(`Added "${drop.scenario.name}" from ${plan.project.name}.${added}`, "success");
      } catch (err: any) {
        showToast(err?.message || "The scenario could not be added.", "error");
      }
    },
    [
      ensureProjectId, showToast, reactFlow, workflowNameRef, workflowGoal, scenarios, loadTrill,
      setOutputs, hydrateRestoredOutputs, setScenarios, markDirty,
    ],
  );
}

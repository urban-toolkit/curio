import { useCallback, useMemo, useRef } from "react";
import { useReactFlow } from "reactflow";
import { v4 as uuid } from "uuid";

import { useCode } from "../../hook/useCode";
import { hostedGuestSignInNote, useHostedGuest } from "../apiSettings/useHostedGuest";
import { useFlowContext } from "../../providers/FlowProvider";
import { useToastContext, type ToastVariant } from "../../providers/ToastProvider";
import { refreshPackageRegistry } from "../../registry/packageRegistryBootstrap";
import { setCurrentProjectPackages } from "../../registry/projectPackagesStore";
import { buildDatasetLoaderNodeOptions } from "../../services/datasetCatalog";
import { runsApi, type RunStatus } from "../../services/runs/runsApi";
import { scenarioCatalogApi, type ScenarioCopyPlan, type ScenarioDragPayload } from "../../services/scenarioCatalog";
import { TrillGenerator } from "../../TrillGenerator";
import { restoredByNode, restoredOutputs, withOutputs } from "../../utils/restoredOutputs";
import { dropGraph, loaderNodes, planScenarioDrop } from "../../utils/scenarios/scenarioDrop";
import { liveScenarios } from "../../utils/scenarios/scenarioParts";

/** What a scenario drop added. */
export interface DroppedScenario {
  /** The ids of the nodes the drop added. */
  nodes: string[];
  /** The id of the scenario it added. */
  scenario: string;
}

/** "A", "A and B", "A, B and C". */
function listed(labels: string[]): string {
  return labels.length < 2 ? labels.join("") : `${labels.slice(0, -1).join(", ")} and ${labels[labels.length - 1]}`;
}

/**
 * Run the context nodes the plan lists to run (`toRun`) on the server, in the
 * scenario's own project, whose run saves their outputs there, and follow the
 * run to its end. A run already going in that project is followed instead.
 * Resolves to why the outputs were not made, or null once the run succeeded.
 */
async function runContext(
  plan: ScenarioCopyPlan,
  showToast: (message: string, variant?: ToastVariant) => void,
): Promise<string | null> {
  const nodes = `${listed(plan.toRun.map((node) => node.label))} in ${plan.project.name}`;
  showToast(`Running ${nodes} for ${plan.scenario.name}`, "info");
  let runId: string;
  try {
    runId = (await runsApi.start(plan.project.id, { targets: plan.toRun.map((node) => node.nodeId) })).id;
  } catch (err: any) {
    const running = err?.status === 409 ? err?.body?.runId : null;
    if (!running) return `${nodes} could not run: ${err?.message || "the run did not start."}`;
    runId = running;
  }
  let ended = null as RunStatus | null;
  const errors: string[] = [];
  await runsApi.follow(runId, (event) => {
    if (event.kind === "step_finished" && event.status === "error" && event.stderrTail) {
      errors.push(event.stderrTail.trim());
    } else if (event.kind === "run_finished") {
      ended = event.status;
    }
  });
  if (ended === "succeeded") return null;
  return `${nodes} did not run${errors.length > 0 ? `: ${errors.join(" ")}` : "."}`;
}

/**
 * A scenario dragged from the Scenario Catalog onto this canvas (#662).
 *
 * The server says what the drop copies and whether it can (a package that
 * cannot be added, a context only the browser can make); a context node with
 * no saved output runs first on the server, in the scenario's project, and
 * the server is asked again; the canvas picks the copies' ids
 * (`planScenarioDrop`); the server then adds the packages and copies the
 * saved outputs to those ids; and the canvas loads the copies the way
 * Duplicate selection does, with the copied outputs restored the way opening
 * a project restores them, and adds the scenario collapsed.
 *
 * Resolves to what it added, null when the drop is refused.
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
  // Read once the drop's run has ended, which can be long after the drop.
  const scenariosRef = useRef(scenarios);
  scenariosRef.current = scenarios;
  const { loadTrill } = useCode();
  const reactFlow = useReactFlow();
  const { showToast } = useToastContext();
  const hostedGuest = useHostedGuest();

  return useCallback(
    async (payload: ScenarioDragPayload, at: { x: number; y: number }): Promise<DroppedScenario | null> => {
      const target = await ensureProjectId();
      if (!target) {
        // A hosted guest gets no id for a dataflow it never saved, and cannot
        // save one, so it is told to sign in rather than to save first.
        showToast(
          hostedGuest
            ? hostedGuestSignInNote("add scenarios")
            : "Save this dataflow first, then drag the scenario again.",
          "warning",
        );
        return null;
      }
      try {
        let plan = await scenarioCatalogApi.getCopyPlan(payload.projectId, payload.scenarioId, target);
        if (plan.problems.length === 0 && plan.toRun.length > 0) {
          const failed = await runContext(plan, showToast);
          if (failed) {
            showToast(failed, "error");
            return null;
          }
          plan = await scenarioCatalogApi.getCopyPlan(payload.projectId, payload.scenarioId, target);
        }
        if (plan.problems.length > 0) {
          showToast(plan.problems.join(" "), "error");
          return null;
        }
        if (plan.toRun.length > 0) {
          showToast(
            `${listed(plan.toRun.map((node) => node.label))} in ${plan.project.name} has no saved output after its run: `
              + `drag "${plan.scenario.name}" again.`,
            "error",
          );
          return null;
        }
        const scenarios = scenariosRef.current;
        const live = TrillGenerator.generateTrill(
          reactFlow.getNodes(), reactFlow.getEdges(), workflowNameRef.current, workflowGoal,
        );
        const drop = planScenarioDrop(plan, live.dataflow, scenarios, { newId: uuid, at });
        if ("error" in drop) {
          showToast(drop.error, "warning");
          return null;
        }
        const copied = await scenarioCatalogApi.copyInto(payload.projectId, payload.scenarioId, target, drop.outputs);
        if (copied.added.length > 0) {
          // As the Node Catalog's Add does, and before the nodes that use them
          // are built, so none of them comes up as an unknown kind.
          setCurrentProjectPackages(copied.packages);
          await refreshPackageRegistry();
        }
        const graph = dropGraph(drop, loaderNodes(drop.loaders, copied.datasets, buildDatasetLoaderNodeOptions));
        // No load fit: it frames the nodes React Flow measures, and the box is
        // not one and its members are hidden, so it framed the context alone
        // and left the box out of view. The canvas brings the box into sight
        // once it is drawn (#769).
        const loaded = loadTrill(
          { dataflow: { ...live.dataflow, nodes: graph.nodes, edges: graph.edges } },
          "none",
          undefined,
          restoredByNode(copied.outputs),
          { fit: false },
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
        const before = new Set(live.dataflow.nodes.map((node: { id: string }) => node.id));
        return {
          nodes: graph.nodes.map((node) => node.id).filter((id) => !before.has(id)),
          scenario: drop.scenario.id,
        };
      } catch (err: any) {
        showToast(err?.message || "The scenario could not be added.", "error");
        return null;
      }
    },
    [
      ensureProjectId, showToast, hostedGuest, reactFlow, workflowNameRef, workflowGoal, loadTrill,
      setOutputs, hydrateRestoredOutputs, setScenarios, markDirty,
    ],
  );
}

/**
 * Wraps children and loads a project from the URL param `:id`.
 *
 * On mount, if the URL has a project UUID (not "new"), it fetches the project
 * from the API, applies the spec via loadParsedTrill, and pre-populates
 * FlowContext.outputs so every node renders in an executed state.
 */
import React, { useEffect, useRef } from "react";
import { useParams } from "react-router-dom";
import { useFlowContext, IOutput } from "../providers/FlowProvider";
import { useCode } from "../hook/useCode";
import { TrillGenerator } from "../TrillGenerator";
import { refreshPackRegistry } from "../registry/packRegistryBootstrap";

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function hasLoadableDataflow(
  spec: unknown
): spec is { dataflow: { nodes: unknown[]; edges: unknown[] } } {
  if (!spec || typeof spec !== "object") return false;
  const dataflow = (spec as { dataflow?: { nodes?: unknown[]; edges?: unknown[] } })
    .dataflow;
  return Boolean(
    dataflow && Array.isArray(dataflow.nodes) && Array.isArray(dataflow.edges)
  );
}

export const ProjectLoader: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { id } = useParams<{ id?: string }>();
  const loaded = useRef<string | null>(null);
  const {
    loadProject,
    loadSharedProject,
    setOutputs,
    loadParsedTrill,
    projectId,
  } = useFlowContext();
  const { loadTrill } = useCode();

  useEffect(() => {
    if (id === "new") {
      TrillGenerator.reset();
      return;
    }
    if (!id || !UUID_RE.test(id)) return;
    if (loaded.current === id) return;
    if (projectId === id) return;

    loaded.current = id;

    const applyResult = (result: { spec: unknown; outputs?: Array<{ node_id: string; filename: string }> }) => {
      const { spec, outputs } = result;

      if (spec) {
        if (!hasLoadableDataflow(spec)) {
          throw new Error(
            "Project spec is missing a valid dataflow payload. It may have been saved incorrectly."
          );
        }
        loadTrill(spec);
      }

      if (outputs && outputs.length > 0) {
        const newOutputs: IOutput[] = outputs.map((o) => ({
          nodeId: o.node_id,
          output: o.filename,
        }));
        setOutputs((prev: IOutput[]) => {
          const existing = new Set(prev.map((p) => p.nodeId));
          const merged = [...prev];
          for (const o of newOutputs) {
            if (existing.has(o.nodeId)) {
              const idx = merged.findIndex((m) => m.nodeId === o.nodeId);
              if (idx >= 0) merged[idx] = o;
            } else {
              merged.push(o);
            }
          }
          return merged;
        });
      }
    };

    (async () => {
      // Pack descriptors register asynchronously at boot. If a user deep-links
      // straight into /dataflow/<id>, ProjectLoader can mount before
      // `refreshPackRegistry()` resolves, leaving `getNodeDescriptor()` calls in
      // loadTrill with no built-in descriptors to find. Await pack discovery
      // before applying the spec so every node has a registered kind.
      try {
        await refreshPackRegistry();
      } catch {
        /* loader continues; descriptor-miss surfaces per-node, not as a hard stop */
      }
      try {
        const result = await loadProject(id);
        applyResult(result);
      } catch (err) {
        // 404 from the owner-scoped endpoint means either the project doesn't
        // exist or the current user isn't its owner. Try the shared (link-based)
        // endpoint before giving up — it's how share URLs work for visitors.
        const status = (err as { status?: number })?.status;
        if (status === 404) {
          try {
            const result = await loadSharedProject(id);
            applyResult(result);
            return;
          } catch (sharedErr) {
            console.error("Failed to load shared project:", sharedErr);
            return;
          }
        }
        console.error("Failed to load project:", err);
      }
    })();
  }, [id]);

  return <>{children}</>;
};

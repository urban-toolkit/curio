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
import { refreshPackageRegistry } from "../registry/packageRegistryBootstrap";
import {
  clearCurrentProject,
  setCurrentProject,
} from "../registry/projectPackagesStore";

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
      // No project loaded — palette shows every installed package. The new
      // project's lockfile will be seeded from per-user defaults on first save.
      clearCurrentProject();
      return;
    }
    if (!id || !UUID_RE.test(id)) return;
    if (loaded.current === id) return;
    if (projectId === id) return;

    loaded.current = id;

    // Pin the project id immediately with an empty lockfile so the palette
    // filter knows we're in a project; loadProject below will replace the
    // package set via setPackages → projectPackagesStore.
    setCurrentProject(id, []);

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
      // Package descriptors register asynchronously at boot. If a user deep-links
      // straight into /dataflow/<id>, ProjectLoader can mount before
      // `refreshPackageRegistry()` resolves, leaving `getNodeDescriptor()` calls in
      // loadTrill with no built-in descriptors to find. We do a two-pass register:
      // first refresh while the lockfile is empty (palette = builtin only), then
      // loadProject populates the lockfile via the store, and refresh runs again
      // so the palette ends up filtered to this project's packages.
      try {
        await refreshPackageRegistry();
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
          } catch (sharedErr) {
            console.error("Failed to load shared project:", sharedErr);
          }
        } else {
          console.error("Failed to load project:", err);
        }
      }
      // Spec applied (or load failed); the store now reflects the project's
      // lockfile (or stays empty on failure). Re-refresh so the palette
      // intersects with the lockfile the store learned from loadParsedTrill.
      try {
        await refreshPackageRegistry();
      } catch {
        /* ditto: descriptor-miss surfaces per-node */
      }
    })();
  }, [id]);

  return <>{children}</>;
};

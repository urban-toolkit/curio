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
import { useToastContext } from "../providers/ToastProvider";
import { TrillGenerator } from "../TrillGenerator";
import { packagesApi } from "../api/packagesApi";
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
  const { showToast } = useToastContext();

  // Fire-and-forget: warn about Python libs the loaded dataflow needs but
  // the interpreter is missing (inline node imports + lockfile manifest
  // deps), then auto-install them. Non-blocking — the canvas stays usable
  // while pip runs; nodes executed before it finishes fail with a normal
  // ModuleNotFoundError and succeed on re-run.
  //
  // SECURITY: only ever called for the OWNER's own project. The package
  // names come from node source the loader can't vet, and installing an
  // sdist runs setup.py server-side — so we never auto-install for a
  // foreign/shared spec (see the loadSharedProject path below, which is a
  // read-only public link the visitor can't execute nodes on anyway).
  const ensureWorkflowDeps = (spec: {
    dataflow: { nodes: unknown[]; packages?: unknown };
  }) => {
    const nodes = spec.dataflow.nodes
      .map((n) => ({
        content:
          n && typeof (n as { content?: unknown }).content === "string"
            ? ((n as { content: string }).content)
            : "",
      }))
      .filter((n) => n.content.trim() !== "");
    const packages = Array.isArray(spec.dataflow.packages)
      ? (spec.dataflow.packages as unknown[]).filter(
          (p): p is string => typeof p === "string"
        )
      : [];
    if (nodes.length === 0 && packages.length === 0) return;
    void (async () => {
      // The check is best-effort: a failure here (older backend without the
      // route, a transient dev-reloader restart) must stay silent — like the
      // refreshPackageRegistry catches below — and never assert an install
      // failure for deps that may not even be missing.
      let missing: Array<{ name: string; spec: string }>;
      try {
        const probe = await packagesApi.checkWorkflowDeps(nodes, packages);
        missing = probe.missing;
      } catch (err) {
        console.error("Workflow dependency check failed:", err);
        return;
      }
      if (!missing.length) return;
      const names = missing.map((m) => m.name).join(", ");
      showToast(
        `This dataflow needs Python packages that are not installed: ${names} — installing them now…`,
        "warning"
      );
      try {
        const deps: Record<string, string> = {};
        for (const m of missing) deps[m.name] = m.spec || "";
        await packagesApi.installWorkflowDeps(deps);
        showToast(`Installed ${names}.`, "success");
      } catch (err) {
        console.error("Workflow dependency install failed:", err);
        showToast(
          `Could not install ${names} — nodes may fail until these are installed manually.`,
          "error"
        );
      }
    })();
  };

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

    const applyResult = (
      result: { spec: unknown; outputs?: Array<{ node_id: string; filename: string }> },
      { trusted }: { trusted: boolean }
    ) => {
      const { spec, outputs } = result;

      if (spec) {
        if (!hasLoadableDataflow(spec)) {
          throw new Error(
            "Project spec is missing a valid dataflow payload. It may have been saved incorrectly."
          );
        }
        loadTrill(spec);
        // Auto-install missing deps only for the owner's own project — never
        // for a foreign shared spec (see ensureWorkflowDeps' SECURITY note).
        if (trusted) ensureWorkflowDeps(spec);
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
        applyResult(result, { trusted: true });
      } catch (err) {
        // 404 from the owner-scoped endpoint means either the project doesn't
        // exist or the current user isn't its owner. Try the shared (link-based)
        // endpoint before giving up — it's how share URLs work for visitors.
        // trusted=false: the shared spec is foreign content, so we render it
        // but never auto-install its declared deps.
        const status = (err as { status?: number })?.status;
        if (status === 404) {
          try {
            const result = await loadSharedProject(id);
            applyResult(result, { trusted: false });
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

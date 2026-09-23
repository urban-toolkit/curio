/**
 * Wraps children and loads a project from the URL param `:id`.
 *
 * On mount, if the URL has a project UUID (not "new"), it fetches the project
 * from the API, applies the spec via loadParsedTrill, and pre-populates
 * FlowContext.outputs so every node renders in an executed state.
 */
import React, { useEffect, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useFlowContext, IOutput } from "../providers/FlowProvider";
import { useCode } from "../hook/useCode";
import { useEnsureWorkflowDeps } from "../hook/useEnsureWorkflowDeps";
import { TrillGenerator } from "../TrillGenerator";
import { refreshPackageRegistry } from "../registry/packageRegistryBootstrap";
import {
  beginProjectLoad,
  setCurrentProject,
  setCurrentProjectPackages,
  settleProjectLoad,
  setUnsavedDataflow,
} from "../registry/projectPackagesStore";
import { packagesApi } from "../api/packagesApi";
import { useToastContext } from "../providers/ToastProvider";
import { loadFailedMessage } from "../utils/dataflowImport";

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Shown when neither the owner-scoped nor the shared endpoint could produce the
 * project (#350). Deliberately does not distinguish "does not exist" from "not
 * yours": the 404 the owner endpoint returns means both, and guessing which
 * would either leak the existence of someone else's project or mislead.
 */
export const PROJECT_LOAD_FAILED_MESSAGE =
  "That project could not be opened. It may have been deleted, or the link may not be shared with you.";

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
  const navigate = useNavigate();
  const { showToast } = useToastContext();
  const loaded = useRef<string | null>(null);
  const {
    loadProject,
    loadSharedProject,
    setOutputs,
    hydrateRestoredOutputs,
    loadParsedTrill,
    projectId,
  } = useFlowContext();
  const { loadTrill } = useCode();
  // Warn + auto-install missing Python deps. SECURITY: only called for the
  // OWNER's own project below — never for a foreign/shared spec, since the
  // package names come from node source the loader can't vet and installing
  // an sdist runs setup.py server-side (see the hook's doc comment).
  const ensureWorkflowDeps = useEnsureWorkflowDeps();

  // Canonicalize the URL when a brand-new dataflow gets persisted out-of-band —
  // e.g. installing a dataset or a producing node's auto-install creates+saves
  // the project (setting projectId) without going through the Save button's
  // navigate. Without this the URL stays /dataflow/new, so a reload would reset
  // to a fresh canvas and drop the just-created project. Mirrors the
  // first-save navigate in UpMenu.handleSave; the [id] effect below then bails
  // via its `projectId === id` guard, so no reload/re-fetch occurs.
  useEffect(() => {
    if (id === "new" && projectId && UUID_RE.test(projectId)) {
      navigate(`/dataflow/${projectId}`, { replace: true });
    }
  }, [id, projectId, navigate]);

  useEffect(() => {
    // ``/dataflow`` with no id at all reaches the same canvas as
    // ``/dataflow/new`` (the route param is optional), so it has to take the
    // same branch. It used to fall through the UUID guard below and pin
    // nothing, inheriting whatever the previous dataflow left in the store.
    if (!id || id === "new") {
      TrillGenerator.reset();
      // An unsaved dataflow is still a dataflow, so it gets a scope rather than
      // "no project, show everything" — that fallback is what put the previous
      // dataflow's packages in a brand-new one (#204, #220).
      //
      // Start empty (builtin always passes the filter) so the leak stops on the
      // same tick, then widen to the account defaults, which is what the backend
      // merges into the lockfile on first save. The palette therefore shows the
      // same set before and after that save.
      setUnsavedDataflow([]);
      let cancelled = false;
      packagesApi
        .getDefaults()
        .then((resp) => {
          // Only if we are still on the unsaved dataflow: a fast navigation to a
          // real project must not have its lockfile overwritten by this reply.
          if (!cancelled) setCurrentProjectPackages(resp.packages ?? []);
        })
        .catch(() => {
          // Leaving the scope empty is the safe failure: the palette shows the
          // builtin package only, rather than every package the account owns.
        });
      return () => {
        cancelled = true;
      };
    }
    if (!UUID_RE.test(id)) return;
    if (loaded.current === id) return;
    if (projectId === id) return;

    loaded.current = id;

    // Pin the project id immediately with an empty lockfile so the palette
    // filter knows we're in a project; loadProject below will replace the
    // package set via setPackages → projectPackagesStore.
    setCurrentProject(id, []);
    // ...and open the latch that says this dataflow is being loaded, so a save
    // fired before the load lands waits for it instead of reading the empty
    // flow state as "never saved" and creating a second dataflow (#340).
    beginProjectLoad(id);

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
        // Refill downstream data.input (incl. merge slots) from the restored
        // outputs — otherwise every reload requires rerunning each upstream
        // node before merges/pools receive anything (dev/64).
        hydrateRestoredOutputs(newOutputs);
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
        // Log AND toast, never log instead of toasting (the UpMenu rule). A
        // console.error is the only trace a user gets otherwise, and the canvas
        // just sits there empty - indistinguishable from an empty project,
        // which is #350. The File > Load picker got this treatment in #251;
        // this is the same failure through the /dataflow/:id route.
        if (status === 404) {
          try {
            const result = await loadSharedProject(id);
            applyResult(result, { trusted: false });
          } catch (sharedErr) {
            console.error("Failed to load shared project:", sharedErr);
            // Two different failures land here: the shared endpoint refusing
            // (a status, so genuinely not reachable) and applyResult throwing
            // on a spec it did fetch (no status, and its own sentence says
            // more than "may have been deleted" would).
            showToast(
              (sharedErr as { status?: number })?.status
                ? PROJECT_LOAD_FAILED_MESSAGE
                : loadFailedMessage(sharedErr),
              "error",
            );
          }
        } else {
          console.error("Failed to load project:", err);
          // A malformed stored spec arrives here too: applyResult's throw
          // carries a sentence written for the user, so pass it through rather
          // than replacing it with the generic one.
          showToast(loadFailedMessage(err), "error");
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
      // The latch opens in the ``finally`` below, which is both LAST and on
      // every path including the failures handled above. Last because on this
      // side of it the canvas carries the stored spec: a save that was waiting
      // then persists this dataflow rather than the empty canvas it would have
      // caught a moment earlier, which would be a wipe rather than a fork.
    })().finally(() => settleProjectLoad(id));
  }, [id]);

  return <>{children}</>;
};

/**
 * Wraps children and loads a project from the URL param `:id`.
 *
 * On mount, if the URL has a project UUID (not "new"), it fetches the project
 * from the API, applies the spec via loadParsedTrill, and pre-populates
 * FlowContext.outputs so every node renders in an executed state. On
 * `/dataflow/new` it sets up an unsaved dataflow, empty or holding the file
 * File > Load picked.
 */
import React, {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useFlowContext, IOutput } from "../providers/FlowProvider";
import { useCode } from "../hook/useCode";
import { useEnsureWorkflowDeps } from "../providers/packages/useEnsureWorkflowDeps";
import { TrillGenerator } from "../TrillGenerator";
import { refreshPackageRegistry } from "../registry/packageRegistryBootstrap";
import {
  beginProjectLoad,
  setCurrentProject,
  setCurrentProjectPackages,
  settleProjectLoad,
  setUnsavedDataflow,
} from "../registry/projectPackagesStore";
import { packagesApi } from "../services/packages";
import { useToastContext } from "../providers/ToastProvider";
import { loadFailedMessage } from "../utils/dataflowImport";
import {
  hasOpenedDataflowFile,
  openedDataflowFileRevision,
  subscribeOpenedDataflowFile,
  takeOpenedDataflowFile,
} from "../utils/openedDataflowFile";
import { restoredByNode, restoredOutputs, withOutputs } from "../utils/restoredOutputs";

import { SHARE_UUID_RE as UUID_RE } from "../utils/shareLinks";
import { dashboardRefusal, getEmbeddedDashboard } from "../standalone/dashboardPayload";

/** How far the load has got, for a page that has to say which state it is in. */
export type ProjectLoadState = "idle" | "loading" | "loaded" | "failed";

const ProjectLoadStateContext = createContext<ProjectLoadState>("idle");

/**
 * The load's progress.
 *
 * The dashboard needs it to tell three things apart that all render as an empty
 * page: still loading, loaded with nothing pinned, and could not be opened. The
 * canvas has its own chrome to say so and ignores this.
 */
export function useProjectLoadState(): ProjectLoadState {
  return useContext(ProjectLoadStateContext);
}

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

export const ProjectLoader: React.FC<{
  children: React.ReactNode;
  /** Loading for the dashboard page rather than the canvas. */
  presentation?: boolean;
}> = ({ children, presentation = false }) => {
  const { id } = useParams<{ id?: string }>();
  const navigate = useNavigate();
  const [loadState, setLoadState] = useState<ProjectLoadState>("idle");
  const { showToast } = useToastContext();
  const loaded = useRef<string | null>(null);
  const {
    loadProject,
    loadSharedProject,
    setOutputs,
    hydrateRestoredOutputs,
    loadParsedTrill,
    projectId,
    attachLatestRun,
    markDirty,
    setWorkflowName,
  } = useFlowContext();
  // Read when the load answers, not when it started: whether this canvas runs
  // on the server depends on the signed-in user, which can arrive in between.
  const attachLatestRunRef = useRef(attachLatestRun);
  attachLatestRunRef.current = attachLatestRun;
  const { loadTrill } = useCode();
  // Warn + auto-install missing Python deps. SECURITY: only called for the
  // OWNER's own project below — never for a foreign/shared spec, since the
  // package names come from node source the loader can't vet and installing
  // an sdist runs setup.py server-side (see the hook's doc comment).
  const ensureWorkflowDeps = useEnsureWorkflowDeps();
  // Bumped each time File > Load hands over a file, which on an unsaved
  // dataflow arrives without a route change.
  const openedFileRevision = useSyncExternalStore(
    subscribeOpenedDataflowFile,
    openedDataflowFileRevision,
  );

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
      // A file File > Load picked brings its own lockfile, which the effect
      // below applies; the defaults would land on top of it.
      if (hasOpenedDataflowFile()) return;
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

    /** Apply a loaded project; returns the nodes whose saved output it restored. */
    const applyResult = (
      result: {
        spec: unknown;
        outputs?: Array<{ node_id: string; filename: string; data_type?: string }>;
      },
      { trusted }: { trusted: boolean }
    ): Set<string> => {
      const { spec, outputs } = result;

      let loaded: { nodes: any[]; edges: any[] } | null = null;
      const restoredIds = new Set<string>();
      if (spec) {
        if (!hasLoadableDataflow(spec)) {
          throw new Error(
            "Project spec is missing a valid dataflow payload. It may have been saved incorrectly."
          );
        }
        // The outputs the manifest restored, by node: those nodes are built as
        // having run, so a downstream play reuses them (#407).
        const restored = restoredByNode(outputs);
        for (const nodeId of Object.keys(restored)) restoredIds.add(nodeId);
        loaded = loadTrill(spec, undefined, undefined, restored);
        // Auto-install missing deps only for the owner's own project — never
        // for a foreign shared spec (see ensureWorkflowDeps' SECURITY note), and
        // never for a dashboard: opening a page to look at it must not install
        // Python packages on the server.
        if (trusted && !presentation) ensureWorkflowDeps(spec);
      }

      if (outputs && outputs.length > 0) {
        const newOutputs = restoredOutputs(outputs);
        setOutputs((prev: IOutput[]) => withOutputs(prev, newOutputs));
        // Refill downstream data.input (incl. input circles) from the restored
        // outputs — otherwise every reload requires rerunning each upstream
        // node before downstream nodes and pools receive anything (dev/64).
        //
        // Against the edges the load just built, not React Flow's store: the
        // store is written from an effect and still reports nothing at this
        // point, so whether the restore reached anyone was a race. It is what a
        // dashboard tile draws from, and it has no Play to fall back on.
        hydrateRestoredOutputs(newOutputs, loaded?.edges);
      }
      return restoredIds;
    };

    setLoadState("loading");
    (async () => {
      // A dashboard the backend would not build as a page of its own: the page
      // carries the backend's reason instead of its data, and the dashboard
      // page shows that. Nothing is loaded, from the page or the network:
      // fetching the data instead is the fallback the refusal rules out.
      if (dashboardRefusal()) {
        const name = getEmbeddedDashboard()?.meta?.name;
        if (name) setWorkflowName(name);
        setLoadState("failed");
        return;
      }
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
      // A standalone dashboard was served with its spec and its rows inside it,
      // so there is nothing to load. Taken before the request, not after a
      // failure: the point of the page is that it never reaches the network.
      //
      // trusted=false, like a shared spec. A page anyone can open by link must
      // not auto-install the dependencies its spec declares, and `presentation`
      // already blocks that, but saying so twice costs nothing and the day this
      // payload is served on another route it will still be foreign content.
      const embedded = getEmbeddedDashboard();
      if (embedded) {
        try {
          applyResult(
            { spec: embedded.spec, outputs: embedded.outputRefs ?? [] },
            { trusted: false },
          );
          setLoadState("loaded");
        } catch (embeddedErr) {
          console.error("Failed to read the embedded dashboard:", embeddedErr);
          setLoadState("failed");
          showToast(loadFailedMessage(embeddedErr), "error");
        }
        return;
      }

      try {
        const result = await loadProject(id);
        const restored = applyResult(result, { trusted: true });
        setLoadState("loaded");
        // The outputs its last run on the server made that the saved ones do
        // not hold, and that run itself if it is still going. Canvas only: a
        // dashboard draws from what was saved.
        if (!presentation) void attachLatestRunRef.current(id, restored);
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
            setLoadState("loaded");
          } catch (sharedErr) {
            console.error("Failed to load shared project:", sharedErr);
            setLoadState("failed");
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
          setLoadState("failed");
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

  // File > Load (#751): the menu left the open dataflow the way File > New
  // does and handed the picked file over, and it becomes the unsaved dataflow
  // here, after the effect above set that up. Its first save creates a project
  // named after it, which leaves the dataflow that was open as it was.
  useEffect(() => {
    if (id && id !== "new") return;
    const spec = takeOpenedDataflowFile();
    if (!spec) return;
    try {
      loadTrill(spec);
    } catch (err) {
      // A spec can carry the right shape and still throw while it is replayed,
      // on a node type this build does not know.
      console.error("Failed to load dataflow:", err);
      showToast(loadFailedMessage(err), "error");
      return;
    }
    // Nothing of it is on disk yet. The edge replay inside loadParsedTrill
    // does not say so on its own (#229), and never did for an edgeless file.
    markDirty();
    // Loading a file is a deliberate user action, so warn + auto-install its
    // Python deps the same way opening your own project does.
    ensureWorkflowDeps(spec);
  }, [id, openedFileRevision]);

  return (
    <ProjectLoadStateContext.Provider value={loadState}>
      {children}
    </ProjectLoadStateContext.Provider>
  );
};

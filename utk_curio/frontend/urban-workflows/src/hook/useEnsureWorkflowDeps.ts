import { useCallback } from "react";
import { useToastContext } from "../providers/ToastProvider";
import { packagesApi } from "../api/packagesApi";
import type { WorkflowDepImportFailure } from "../api/packagesApi";
import { refreshPackageRegistry } from "../registry/packageRegistryBootstrap";
import { dependencyFailureNotice } from "../utils/packageDependencyNotice";

interface DataflowSpec {
  // Index signature avoids TS "weak type" assignability errors when callers
  // pass a spec narrowed to a different dataflow shape (e.g. {nodes, edges}).
  dataflow?: { packages?: unknown } & Record<string, unknown>;
}

/**
 * Returns a fire-and-forget `ensureWorkflowDeps(spec)` that installs the
 * catalog packages a dataflow declares it depends on (`dataflow.packages`)
 * but the user hasn't installed yet - except the ones the backend marks
 * `deferred`, which are too expensive to install unasked (see
 * `packages/seed.py::INSTALL_ON_DEMAND_PACKAGE_IDS`). Installing a package
 * provisions both its nodes and its declared python libraries — a dataflow
 * depends on packages, and the libraries follow. Non-blocking: the canvas stays usable
 * while pip runs; nodes executed before it finishes fail with a normal
 * ModuleNotFoundError and succeed on re-run.
 *
 * Call this whenever a dataflow is loaded through a deliberate user action
 * (opening your own project, importing a workflow file, generating one from
 * an LLM goal). Do NOT call it for passively-opened foreign content — most
 * notably a read-only shared link the visitor can't execute nodes on — even
 * though package installs are catalog-scoped (no arbitrary pip names),
 * pulling a package into the visitor's store on a drive-by is still wrong.
 */
export function useEnsureWorkflowDeps() {
  const { showToast } = useToastContext();

  return useCallback(
    (spec: DataflowSpec) => {
      const declared = spec?.dataflow?.packages;
      const packages = Array.isArray(declared)
        ? (declared as unknown[]).filter((p): p is string => typeof p === "string")
        : [];
      if (packages.length === 0) return;

      void (async () => {
        // The check is best-effort: a failure here (older backend without the
        // route, a transient dev-reloader restart) stays silent and never
        // asserts an install failure for packages that may already be ready.
        let needed: string[];
        let broken: WorkflowDepImportFailure[];
        try {
          const probe = await packagesApi.checkWorkflowDeps(packages);
          // Anything the backend defers is missing but must not be installed
          // as a side effect of opening a dataflow - `curio.streetvision` is
          // ~3 GB of torch, and the example that needs it says so in its own
          // setup notes. The canvas names it on the node instead, with an
          // Install button, so the user makes that call knowingly (#233).
          const deferred = new Set(probe.deferred ?? []);
          needed = probe.packages.filter((dirName) => !deferred.has(dirName));
          broken = probe.broken ?? [];
        } catch (err) {
          console.error("Workflow dependency check failed:", err);
          return;
        }

        // Installed, version-satisfying, and still not importable — a wheel
        // whose native extension won't load. Say so instead of installing:
        // pip would report "already satisfied" and change nothing, and the
        // user would otherwise meet this as a raw ImportError from whichever
        // node happened to run first.
        if (broken.length) {
          const detail = broken
            .map((b) => `${b.dep} (${b.error})`)
            .join("; ");
          showToast(
            `This dataflow needs ${detail}. The library is installed but cannot be ` +
              `imported, so reinstalling will not help — repair it in the Curio ` +
              `environment before running these nodes.`,
            "error",
          );
        }

        if (!needed.length) return;
        const names = needed.join(", ");
        showToast(
          `This dataflow depends on packages that aren't installed: ${names}. Installing them now…`,
          "warning"
        );
        try {
          const result = await packagesApi.installWorkflowDeps(needed);
          // Refresh so the catalog drawer + palette reflect the new packages.
          try {
            await refreshPackageRegistry();
          } catch {
            /* palette refresh is best-effort; install already succeeded */
          }
          // The package arrived, but one of its libraries cannot be imported -
          // pip counts metadata as satisfaction, so this reads as a clean
          // install right up until a node touches the library. Saying
          // "Installed" here would be the last chance to tell them, missed.
          // Drop what the /check toast above already named: that toast fired
          // for exactly the libraries that were installed-but-unimportable, and
          // the install cannot have repaired them (pip counts them satisfied
          // and skips). Repeating them stacks two persistent red toasts about
          // one library.
          const alreadyReported = new Set(broken.map((b) => b.dep));
          const unreported = Object.fromEntries(
            Object.entries(result?.importErrors ?? {}).filter(
              ([lib]) => !alreadyReported.has(lib),
            ),
          );
          const notice = dependencyFailureNotice(`Installed ${names}`, {
            ...result,
            importErrors: unreported,
          });
          if (notice) {
            showToast(notice, "error");
          } else {
            showToast(`Installed ${names}.`, "success");
          }
        } catch (err) {
          console.error("Workflow dependency install failed:", err);
          showToast(
            `Could not install ${names}. Nodes may fail until these are installed manually.`,
            "error"
          );
        }
      })();
    },
    [showToast]
  );
}

import { useCallback } from "react";
import { useToastContext } from "../providers/ToastProvider";
import { packagesApi } from "../api/packagesApi";
import { refreshPackageRegistry } from "../registry/packageRegistryBootstrap";

interface DataflowSpec {
  // Index signature avoids TS "weak type" assignability errors when callers
  // pass a spec narrowed to a different dataflow shape (e.g. {nodes, edges}).
  dataflow?: { packages?: unknown } & Record<string, unknown>;
}

/**
 * Returns a fire-and-forget `ensureWorkflowDeps(spec)` that installs the
 * catalog packages a dataflow declares it depends on (`dataflow.packages`)
 * but the user hasn't installed yet. Installing a package provisions both
 * its nodes and its declared python libraries — a dataflow depends on
 * packages, and the libraries follow. Non-blocking: the canvas stays usable
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
        try {
          const probe = await packagesApi.checkWorkflowDeps(packages);
          needed = probe.packages;
        } catch (err) {
          console.error("Workflow dependency check failed:", err);
          return;
        }
        if (!needed.length) return;
        const names = needed.join(", ");
        showToast(
          `This dataflow depends on packages that aren't installed: ${names} — installing them now…`,
          "warning"
        );
        try {
          await packagesApi.installWorkflowDeps(needed);
          // Refresh so the catalog drawer + palette reflect the new packages.
          try {
            await refreshPackageRegistry();
          } catch {
            /* palette refresh is best-effort; install already succeeded */
          }
          showToast(`Installed ${names}.`, "success");
        } catch (err) {
          console.error("Workflow dependency install failed:", err);
          showToast(
            `Could not install ${names} — nodes may fail until these are installed manually.`,
            "error"
          );
        }
      })();
    },
    [showToast]
  );
}

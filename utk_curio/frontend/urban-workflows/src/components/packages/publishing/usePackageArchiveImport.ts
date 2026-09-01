import { useCallback, useState } from "react";
import {
  PackagePayload,
  packagesApi,
  refreshPackageRegistry,
} from "../../../api/packagesApi";

/**
 * The ONE package-sideload pathway, shared by the Node Catalog drawer's footer
 * and the Node Catalog page's header.
 *
 * It exists because the page grew an import of its own and immediately became a
 * second copy of the drawer's: same upload call, same registry refresh, same
 * reload, drifting independently from then on. Both call this now, so a change
 * to how a `.curio.zip` is taken in lands on both surfaces at once.
 *
 * The one real difference between the two callers is the project: the drawer
 * runs inside an open dataflow and drops the new package into that dataflow's
 * lockfile as well, while the page has no dataflow to drop it into. That is
 * expressed as `projectId` being null rather than as a separate code path.
 */
export interface PackageArchiveImportOptions {
  /** The open dataflow, when there is one. Null on the standalone page. */
  projectId?: string | null;
  /** Re-read whatever listing the caller renders. */
  reload: () => Promise<void>;
  /** Reported the caller's way: a toast on the page, an error strip in the drawer. */
  onError: (label: string, err: unknown) => void;
  /** Only fires when `projectId` is set, with the project's new package dirNames. */
  onInstalledToProject?: (packages: string[]) => void;
  /** Fires on success with the imported package, for a toast or a selection. */
  onImported?: (pkg: PackagePayload) => void;
}

export function usePackageArchiveImport({
  projectId = null,
  reload,
  onError,
  onInstalledToProject,
  onImported,
}: PackageArchiveImportOptions) {
  const [importing, setImporting] = useState(false);

  const importArchive = useCallback(
    async (file: File) => {
      setImporting(true);
      try {
        // Sideload always goes through the user-store install path; if a
        // project is open, drop the new package into its lockfile too so the
        // palette picks it up.
        const result = await packagesApi.uploadArchive(file, file.name);
        if (projectId) {
          const projResult = await packagesApi.installToProject(
            projectId,
            result.package.dirName,
          );
          onInstalledToProject?.(projResult.packages);
        }
        await refreshPackageRegistry();
        await reload();
        onImported?.(result.package);
        return result;
      } catch (err) {
        onError(`Couldn't import ${file.name}`, err);
        return null;
      } finally {
        setImporting(false);
      }
    },
    [projectId, reload, onError, onInstalledToProject, onImported],
  );

  return { importing, importArchive };
}

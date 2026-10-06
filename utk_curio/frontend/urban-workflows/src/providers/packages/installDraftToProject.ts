import { packagesApi, type InstallResponse } from "../../services/packages";
import { refreshPackageRegistry } from "../../registry/packageRegistryBootstrap";
import { setCurrentProjectPackages } from "../../registry/projectPackagesStore";
import type { FactoryInstallEnvelope } from "../../utils/palettePackageFactoryDraft";

/**
 * Install a template draft into its package and the open project, then
 * refresh the palette: what Save as package node and New node from a Python
 * function do once their draft is built.
 *
 * The package is only in the USER STORE after `factoryInstall`, and
 * `refreshPackageRegistry` filters by the project lockfile, so without the
 * project step the new descriptor is invisible; worse, the backend listings
 * that feed the node catalog scope by store-intersect-lockfile and do not even
 * report a package they skip, so an agent is told the template does not exist.
 * The project step therefore comes before the refresh.
 *
 * `ensureProjectId` rather than a `projectId` (#346): on an unsaved dataflow
 * there is no project id yet, and skipping the scoping left the package in the
 * user store belonging to no project at all. It saves the dataflow first,
 * de-dupes concurrent callers and toasts on failure itself. Saving into an
 * already INSTALLED package that this project's lockfile does not list needs
 * the same step.
 */
export async function installDraftToProject(
  envelope: FactoryInstallEnvelope,
  ensureProjectId: () => Promise<string | null>,
): Promise<InstallResponse> {
  const result = await packagesApi.factoryInstall(envelope);
  const scopedProjectId = await ensureProjectId();
  if (scopedProjectId) {
    const projResult = await packagesApi.installToProject(scopedProjectId, result.package.dirName);
    setCurrentProjectPackages(projResult.packages);
  }
  await refreshPackageRegistry();
  return result;
}

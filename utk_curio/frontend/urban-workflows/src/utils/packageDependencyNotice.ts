/**
 * One phrasing for "the package arrived, its libraries did not work".
 *
 * pip counts matching metadata as satisfaction, so a wheel whose native
 * extension cannot load - a rasterio built against a different GDAL is the
 * everyday case - installs without complaint and reads as a clean install right
 * up until a node touches it. Seven surfaces install packages, and each one is
 * the last place the failure is still connected to the package that brought it
 * in; when they each wrote their own sentence they drifted, and two of them
 * wrote none at all.
 *
 * The backend answers this at its install seam, so every one of those responses
 * carries the same two optional fields:
 *
 *   ``importErrors``     ``{library: reason}`` - installed, cannot be imported.
 *   ``dependencyError``  pip itself failed; the package files are installed
 *                        anyway, on the paths that cannot take them back.
 */

export interface DependencyReport {
  importErrors?: Record<string, string> | null;
  dependencyError?: string | null;
}

/**
 * ``"rasterio cannot be imported (ImportError: ...)"``, joined with ``"; "``
 * for several, or ``null`` when every library works.
 */
export function brokenLibraryClause(
  importErrors?: Record<string, string> | null,
): string | null {
  const broken = Object.entries(importErrors ?? {});
  if (!broken.length) return null;
  return broken
    .map(([lib, reason]) => `${lib} cannot be imported (${reason})`)
    .join("; ");
}

/**
 * The whole sentence a surface should show after an install that landed, or
 * ``null`` when there is nothing to say.
 *
 * *lead* is what that surface calls what just happened - "Added Weather",
 * "Installed curio.weather@1", "Saved Demo". The rest is identical everywhere,
 * deliberately: the same failure should not read as a different problem
 * depending on which button reached it.
 */
export function dependencyFailureNotice(
  lead: string,
  report: DependencyReport | null | undefined,
): string | null {
  // pip's own failure leads. When pip could not install a library, the probe
  // that runs afterwards reports it "not installed" - which is true, and is a
  // restatement of the pip failure rather than a second problem. Leading with
  // the import wording there told the user a library was broken when nothing
  // had been installed at all, and hid the sentence that says why.
  if (report?.dependencyError) {
    return `${lead}, but its libraries could not be installed: ${report.dependencyError}. Nodes needing them will fail until they are installed.`;
  }
  const clause = brokenLibraryClause(report?.importErrors);
  if (clause) {
    return `${lead}, but ${clause}. Nodes needing it will fail until it is repaired.`;
  }
  return null;
}

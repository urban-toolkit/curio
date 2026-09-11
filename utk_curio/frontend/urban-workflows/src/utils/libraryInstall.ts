/**
 * How to read what ``POST /api/packages/libraries`` answers.
 *
 * Extracted from the Installed-libraries modal so the node error panel (#299)
 * reports the same install the same way. Three answers come back looking
 * similar and mean very different things, and the one that bites is the third:
 * a library can install cleanly, satisfy pip, and still raise on import - a
 * wheel whose native extension cannot load reports a good version, so pip
 * declines to do anything and both lists below read as success. Calling that
 * "already installed" is how a broken library stayed invisible until a node
 * touched it, which is exactly the failure this vocabulary exists to name.
 */

/** The shape ``packagesApi.addLibrary`` resolves to. */
export interface AddLibraryResponse {
  installed?: string[];
  skipped?: string[];
  importError?: string | null;
}

export type LibraryInstallVerdict =
  | { kind: "installed" }
  | { kind: "already-installed" }
  | { kind: "cannot-import"; reason: string };

/**
 * Floor on the visible duration of a progress indicator. Pip's "already
 * satisfied" path returns in microseconds; without this gate the bar flashes
 * too fast to register. 800 ms is short enough not to feel laggy and long
 * enough that the user sees the install happen.
 */
export const MIN_PROGRESS_MS = 800;

/**
 * What actually happened, from the route's answer.
 *
 * ``importError`` overrides both lists - that is the rule that must never
 * drift between the two surfaces.
 */
export function readInstallResponse(
  data: AddLibraryResponse,
): LibraryInstallVerdict {
  if (data.importError) {
    return { kind: "cannot-import", reason: data.importError };
  }
  const installed = data.installed?.length ?? 0;
  const skipped = data.skipped?.length ?? 0;
  if (installed === 0 && skipped > 0) return { kind: "already-installed" };
  return { kind: "installed" };
}

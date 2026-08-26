import { useCallback, useRef, useState } from "react";
import type { PackagePayload, ResolveConflict } from "../../../api/packagesApi";
import { packagesApi } from "../../../api/packagesApi";

/**
 * The dev/84 apply-time review for `package.install` proposals.
 *
 * Applying an agent-proposed package install must show the EXISTING package
 * install review (permissions + dependencies + conflicts — the
 * `InstallPermissionsDialog` the Nodes Catalog drawer uses) before anything
 * executes: `beginReview` loads the package row + the pre-install conflict
 * probe and opens the dialog; the dialog's Install button is what fires the
 * actual proposal apply (`confirm`), and Cancel leaves the proposal pending.
 * The dialog is the review surface — the apply endpoint stays the sole
 * execution authority and re-checks conflicts server-side regardless.
 *
 * `beginReview`'s promise settles with the WHOLE flow (apply success, apply
 * failure, or cancel), so the review card's own busy/error handling wraps the
 * dialog round-trip: an apply failure (409 stale, conflict) rejects into the
 * card's error line — no bespoke error surface.
 */
export interface PackageInstallCandidate {
  proposalId: string;
  pkg: PackagePayload;
  conflicts: ResolveConflict[];
}

/** The slice of the apply result this hook reads (dev/105 A3). */
export interface ApplyFollowUps {
  followUpProposals?: string[];
}

export function usePackageInstallReview(
  applyProposal?: (proposalId: string) => Promise<ApplyFollowUps | void>,
): {
  candidate: PackageInstallCandidate | null;
  busy: boolean;
  beginReview: (proposalId: string, dirName: string) => Promise<void>;
  confirm: () => Promise<void>;
  cancel: () => void;
} {
  const [candidate, setCandidate] = useState<PackageInstallCandidate | null>(null);
  const [busy, setBusy] = useState(false);
  const deferredRef = useRef<{ resolve: () => void; reject: (e: unknown) => void } | null>(null);

  const settle = useCallback((error?: unknown) => {
    const deferred = deferredRef.current;
    deferredRef.current = null;
    if (!deferred) return;
    if (error === undefined) deferred.resolve();
    else deferred.reject(error);
  }, []);

  const beginReview = useCallback(
    async (proposalId: string, dirName: string): Promise<void> => {
      if (!dirName) throw new Error("this proposal carries no package dirName");
      // Load the row + probe BEFORE opening the dialog — a load failure
      // rejects straight into the card's error line, nothing half-open.
      //
      // dev/105 A1: TWO feeds, store first. `/api/packages/catalog` is the
      // committed <repo>/packages/ catalog only; a package the user already
      // owns — an agent-authored one in particular, which dev/93 made
      // proposable for exactly this enlist step — lives in the user's store
      // (`/api/packages`) and nowhere else. Looking only at the catalog made
      // the review gate refuse "no longer in the Nodes Catalog" for a package
      // the backend apply would have installed. Same PackagePayload shape.
      const [store, catalog] = await Promise.all([
        packagesApi.listInstalled(),
        packagesApi.catalog(),
      ]);
      const pkg =
        store.packages.find((p) => p.dirName === dirName) ??
        catalog.packages.find((p) => p.dirName === dirName);
      if (!pkg) {
        throw new Error(
          `package ${dirName} is no longer in the Nodes Catalog or your installed packages`,
        );
      }
      // The drawer's pre-install probe shape: every user-store package plus
      // the candidate, so the conflict report matches what install would hit.
      // The store feed IS that set; the catalog's `installed` flag only covers
      // catalog packages and would miss store-only ones.
      const installed = store.packages.map((p) => p.dirName);
      let conflicts: ResolveConflict[] = [];
      try {
        const probe = await packagesApi.resolve([
          ...installed.filter((d) => d !== dirName),
          dirName,
        ]);
        conflicts = probe.conflicts;
      } catch (err) {
        // The resolve route answers a real conflict report with a 409 body.
        const status = (err as { status?: number }).status;
        if (status === 409) {
          conflicts =
            (err as { body?: { conflicts?: ResolveConflict[] } }).body?.conflicts ?? [];
        } else {
          throw err;
        }
      }
      setCandidate({ proposalId, pkg, conflicts });
      return new Promise<void>((resolve, reject) => {
        deferredRef.current = { resolve, reject };
      });
    },
    [],
  );

  const confirm = useCallback(async () => {
    if (!candidate || busy) return;
    setBusy(true);
    try {
      if (!applyProposal) throw new Error("applying proposals is not available here");
      const result = await applyProposal(candidate.proposalId);
      // dev/105 A3: the install apply queued the Researcher's note cards
      // below the install card; walk them ONE AT A TIME — each apply paints
      // its node and refreshes the transcript before the next card is
      // applied, so the progression is real events, not timers. A failing
      // step stops the walk; the remaining cards stay pending, applicable
      // by hand — nothing is lost.
      for (const followUpId of result?.followUpProposals ?? []) {
        await applyProposal(followUpId);
      }
      setCandidate(null);
      settle();
    } catch (err) {
      setCandidate(null);
      settle(err);
    } finally {
      setBusy(false);
    }
  }, [candidate, busy, applyProposal, settle]);

  const cancel = useCallback(() => {
    if (busy) return; // an install in flight cannot be cancelled client-side
    setCandidate(null);
    settle(); // no error: the proposal simply stays pending
  }, [busy, settle]);

  return { candidate, busy, beginReview, confirm, cancel };
}

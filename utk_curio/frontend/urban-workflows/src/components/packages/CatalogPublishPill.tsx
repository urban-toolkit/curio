import React, { memo, useState } from "react";
import ConfirmDialog from "../ConfirmDialog";
import styles from "./CatalogPublishPill.module.css";

export type CatalogPublishPillVariant = "dock" | "hub";

/**
 * Shared visibility rule for the publish pill, used by every catalog card, row
 * and drawer in both catalogs so the affordance appears under identical
 * conditions. The pill renders for two distinct cases:
 *   - The item is already published — show the "Published" badge (purely
 *     informational; no click handler needed, so ``canPublish`` may be false).
 *   - The operator allows publishing AND the caller can act on this item
 *     (it has a publish handler and is not read-only) — show the "Publish" button.
 */
export function shouldShowPublishPill({
    isPublished,
    allowPublish,
    canPublish,
}: {
    isPublished?: boolean;
    allowPublish: boolean;
    canPublish: boolean;
}): boolean {
    return isPublished === true || (allowPublish && canPublish);
}

export const CatalogPublishPill = memo(function CatalogPublishPill({
    dirName,
    published,
    allowPublish,
    busy,
    onPublish,
    variant = "dock",
    publishedTitle,
    publishActionTitle,
    itemLabel,
    catalogLabel,
}: {
    dirName: string;
    published: boolean;
    allowPublish: boolean;
    busy: boolean;
    onPublish: (dirName: string) => void;
    variant?: CatalogPublishPillVariant;
    /** Tooltip when ``published`` (defaults to package-catalog copy). */
    publishedTitle?: string;
    /** Tooltip on the Publish action (defaults to package-catalog copy). */
    publishActionTitle?: string;
    /** What is being published, for the confirmation's heading. */
    itemLabel?: string;
    /** Where it goes, for the confirmation's body. */
    catalogLabel?: string;
}) {
    const pillCls = variant === "hub" ? styles.pillHub : styles.pillDock;
    const badgeCls = variant === "hub" ? styles.badgeHub : styles.badgeDock;
    // Declared before the early returns below - hooks may not be conditional.
    const [confirmOpen, setConfirmOpen] = useState(false);

    if (published) {
        const title = publishedTitle ?? "Listed in the shared catalog (packages/)";
        // role="status" so the state change is announced when a publish action
        // swaps the button out for this badge — the Data Catalog drawer used to
        // do this on its own bespoke element; every surface gets it now.
        return (
            <span className={badgeCls} role="status" aria-label={title} title={title}>
                {/* A tick, so the state cannot be mistaken for a button. The
                    action beside it used to be the LOUDER of the two - a filled
                    blue uppercase pill reading "PUBLISH", which looks exactly
                    like a status chip saying it had been published. */}
                <span aria-hidden>✓ </span>Published
            </span>
        );
    }
    // When the operator disabled publish (env var CURIO_ALLOW_FACTORY_CATALOG_PUBLISH=0
    // or `--no-allow-publish` on the launcher), the button is hidden entirely
    // rather than disabled — see docs/NODE-CATALOG.md § Operator notes.
    if (!allowPublish) return null;
    const what = itemLabel ?? "this package";
    const where = catalogLabel ?? "the shared catalog";
    return (
        <>
            <button
                type="button"
                className={pillCls}
                disabled={busy}
                title={publishActionTitle ?? "Publish this installed package into the shared catalog (packages/)"}
                onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    setConfirmOpen(true);
                }}
            >
                {/* A verb in sentence case. The uppercase form read as a
                    status chip saying the thing was already published. */}
                {busy ? "…" : "Publish"}
            </button>
            {confirmOpen ? (
                <ConfirmDialog
                    title={`Publish ${what}?`}
                    // Publishing is the only write in the product that leaves
                    // this account: it copies into the deployment-wide catalog
                    // root, where everyone on this Curio can see and install it.
                    // It was also the only one that happened on a single
                    // unconfirmed click, while its inverse asked first.
                    body={
                        `Publish ${what} to ${where}?

` +
                        `Everyone using this Curio will be able to see it and add it ` +
                        `to their own dataflows. You can unpublish it later.`
                    }
                    confirmLabel="Publish"
                    // The catalogs render this from inside a drawer, which
                    // paints above the default modal layer.
                    layer="overlay"
                    onCancel={() => setConfirmOpen(false)}
                    onConfirm={() => {
                        setConfirmOpen(false);
                        void onPublish(dirName);
                    }}
                />
            ) : null}
        </>
    );
});

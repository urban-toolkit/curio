import React, { memo } from "react";
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
}) {
    const pillCls = variant === "hub" ? styles.pillHub : styles.pillDock;
    const badgeCls = variant === "hub" ? styles.badgeHub : styles.badgeDock;

    if (published) {
        const title = publishedTitle ?? "Listed in the shared catalog (packages/)";
        // role="status" so the state change is announced when a publish action
        // swaps the button out for this badge — the Data Catalog drawer used to
        // do this on its own bespoke element; every surface gets it now.
        return (
            <span className={badgeCls} role="status" aria-label={title} title={title}>
                Published
            </span>
        );
    }
    // When the operator disabled publish (env var CURIO_ALLOW_FACTORY_CATALOG_PUBLISH=0
    // or `--no-allow-publish` on the launcher), the button is hidden entirely
    // rather than disabled — see docs/NODE-CATALOG.md § Operator notes.
    if (!allowPublish) return null;
    return (
        <button
            type="button"
            className={pillCls}
            disabled={busy}
            title={publishActionTitle ?? "Publish this installed package into the shared catalog (packages/)"}
            onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                void onPublish(dirName);
            }}
        >
            {busy ? "…" : "Publish"}
        </button>
    );
});

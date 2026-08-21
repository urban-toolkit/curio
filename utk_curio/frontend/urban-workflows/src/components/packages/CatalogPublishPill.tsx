import React, { memo } from "react";
import styles from "./CatalogPublishPill.module.css";

export type CatalogPublishPillVariant = "dock" | "hub";

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
        return (
            <span
                className={badgeCls}
                title={publishedTitle ?? "Listed in the package catalog (packages/)"}
            >
                Published
            </span>
        );
    }
    // When the operator disabled publish (env var CURIO_ALLOW_FACTORY_CATALOG_PUBLISH=0
    // or `--no-allow-publish` on the launcher), the button is hidden entirely
    // rather than disabled — see docs/CATALOG.md § Operator notes.
    if (!allowPublish) return null;
    return (
        <button
            type="button"
            className={pillCls}
            disabled={busy}
            title={publishActionTitle ?? "Write this installed package into packages/ for the dev catalog"}
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

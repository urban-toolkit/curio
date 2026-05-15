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
}: {
    dirName: string;
    published: boolean;
    allowPublish: boolean;
    busy: boolean;
    onPublish: (dirName: string) => void;
    variant?: CatalogPublishPillVariant;
}) {
    const pillCls = variant === "hub" ? styles.pillHub : styles.pillDock;
    const badgeCls = variant === "hub" ? styles.badgeHub : styles.badgeDock;

    if (published) {
        return (
            <span className={badgeCls} title="Listed in the fixture catalog (fixtures/packs)">
                Published
            </span>
        );
    }
    return (
        <button
            type="button"
            className={pillCls}
            disabled={!allowPublish || busy}
            title={
                allowPublish
                    ? "Write this installed pack into fixtures/packs for the dev catalog"
                    : "Catalog fixture publish is disabled on this server"
            }
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

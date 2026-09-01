import React, { memo, useState } from "react";
import ConfirmDialog from "../ConfirmDialog";
import styles from "./CatalogPublishPill.module.css";

/**
 * `dock` - the dark canvas rail. `hub` - a catalog card, a compact 96x30 pill.
 * `drawer` - a browse drawer's action column, where it sits directly under
 * "Add to all projects" and has to match that button's full-width 42px box.
 */
export type CatalogPublishPillVariant = "dock" | "hub" | "drawer";

/**
 * Shared visibility rule: show the control only when there is something to do.
 *
 * It used to be ``isPublished === true || (allowPublish && canPublish)``, so
 * anything already published rendered a static "Published" badge whether or not
 * the viewer had any business acting on it. On the standalone catalog pages
 * that is every single card, because those pages list the shared catalog: the
 * badge told the user that the catalog contains the thing they are looking at
 * in the catalog. It also put an Unpublish beside a shipped dataset the moment
 * it was added to a dataflow, which the user never published and cannot
 * withdraw.
 *
 * So the state is carried by the action, and the action appears only for the
 * user's own things: Publish when it is not published, Unpublish when it is.
 * ``isPublished`` still decides WHICH of the two the pill renders; it no longer
 * decides whether anything renders at all.
 */
export function shouldShowPublishPill({
    allowPublish,
    canPublish,
}: {
    /** Retained for call-site readability; no longer part of the decision. */
    isPublished?: boolean;
    allowPublish: boolean;
    canPublish: boolean;
}): boolean {
    return allowPublish && canPublish;
}

/**
 * One control for the published state, not two, and nothing at all when there
 * is nothing to do.
 *
 * A published item used to render a static "Published" badge here AND a
 * separate "Unpublish" button beside it, so the card said the same thing twice
 * and only one half of it did anything. The state is now carried by the action
 * itself: "Publish" when it is not published, "Unpublish" when it is. That puts
 * both halves under one rule, one confirmation and one place to gate on whether
 * the item is the user's to publish at all.
 *
 * The badge is gone too. It was kept for a while on the theory that "published
 * by someone else" is worth stating, but eight of the thirteen call sites pass
 * no ``onUnpublish``, so in practice it painted "✓ Published" on nearly every
 * card in the product - including every card on the standalone catalog pages,
 * whose entire contents are, by definition, the published catalog. A label that
 * is true of everything on screen distinguishes nothing.
 */
export const CatalogPublishPill = memo(function CatalogPublishPill({
    dirName,
    published,
    allowPublish,
    busy,
    onPublish,
    onUnpublish,
    variant = "dock",
    publishActionTitle,
    unpublishActionTitle,
    itemLabel,
    catalogLabel,
}: {
    dirName: string;
    published: boolean;
    allowPublish: boolean;
    busy: boolean;
    onPublish: (dirName: string) => void;
    /** Withdraws it again. Omit when the viewer may not unpublish this item;
     *  the pill then renders nothing at all for the published state. */
    onUnpublish?: (dirName: string) => void;
    variant?: CatalogPublishPillVariant;
    /** Tooltip on the Publish action (defaults to package-catalog copy). */
    publishActionTitle?: string;
    /** Tooltip on the Unpublish action. */
    unpublishActionTitle?: string;
    /** What is being published, for the confirmation's heading. */
    itemLabel?: string;
    /** Where it goes, for the confirmation's body. */
    catalogLabel?: string;
}) {
    const pillCls =
        variant === "drawer" ? styles.pillDrawer
        : variant === "hub" ? styles.pillHub
        : styles.pillDock;
    const undoCls =
        variant === "drawer" ? styles.undoDrawer
        : variant === "hub" ? styles.undoHub
        : styles.undoDock;
    // Declared before the early returns below - hooks may not be conditional.
    const [confirmOpen, setConfirmOpen] = useState(false);

    const what = itemLabel ?? "this package";
    const where = catalogLabel ?? "the shared catalog";

    if (published) {
        // Published, and not this viewer's to withdraw: nothing to render.
        // This used to be a "✓ Published" badge. See the note above.
        if (!onUnpublish) return null;
        return (
            <>
                <button
                    type="button"
                    className={undoCls}
                    disabled={busy}
                    title={unpublishActionTitle ?? `Remove ${what} from ${where}`}
                    onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        setConfirmOpen(true);
                    }}
                >
                    {busy ? "…" : "Unpublish"}
                </button>
                {confirmOpen ? (
                    <ConfirmDialog
                        title={`Unpublish ${what}?`}
                        body={
                            `Remove ${what} from ${where}?\n\n` +
                            `This removes the listing. Copies already added to dataflows are ` +
                            `not removed.`
                        }
                        confirmLabel="Unpublish"
                        // Cancel keeps initial focus (this is a
                        // deployment-wide write), but not the red paint:
                        // unpublishing removes a listing, destroys nothing, and
                        // is undone by publishing again.
                        destructive
                        tone="plain"
                        layer="overlay"
                        onCancel={() => setConfirmOpen(false)}
                        onConfirm={() => {
                            setConfirmOpen(false);
                            void onUnpublish(dirName);
                        }}
                    />
                ) : null}
            </>
        );
    }
    // When the operator disabled publish (env var CURIO_ALLOW_FACTORY_CATALOG_PUBLISH=0
    // or `--no-allow-publish` on the launcher), the button is hidden entirely
    // rather than disabled — see docs/NODE-CATALOG.md § Operator notes.
    if (!allowPublish) return null;
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
                        `Publish ${what} to ${where}?\n\n` +
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

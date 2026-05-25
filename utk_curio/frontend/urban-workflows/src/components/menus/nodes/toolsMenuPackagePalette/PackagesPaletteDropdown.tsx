import React, { memo, useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import {
    faChevronDown,
    faChevronUp,
    faCube,
} from "@fortawesome/free-solid-svg-icons";
import { packagesApi } from "../../../../api/packagesApi";
import type { PackagePayload } from "../../../../api/packagesApi";
import { subscribeToRegistry } from "../../../../registry";
import { usePackagePalette } from "../../../../providers/PackagePaletteContext";
import { useNodeWarehouseDrawer } from "../../../../providers/NodeWarehouseDrawerProvider";
import { useToastContext } from "../../../../providers/ToastProvider";
import { useStarterContext } from "../../../../providers/StarterProvider";
import { draftFromInstalledPackagePayload } from "../../../../utils/palettePackageFactoryDraft";
import { toApiPayload } from "../../../../pages/nodes/factoryDraftModel";
import { partitionPalettePackageGroups } from "../../../../utils/forkPackageLineage";
import { InstalledPackageAccordion } from "./InstalledPackageAccordion";
import { PaletteForkFamily } from "./PaletteForkFamily";
import { visiblePaletteTriggerPackagesCount, type PackagePaletteGroup } from "./model";
import { paletteDescriptorBootstrapKey } from "./registryBootstrap";
import packageStyles from "./ToolsMenuPackagePalette.module.css";

function escapeCssAttrToken(coord: string): string {
    return typeof CSS !== "undefined" && typeof CSS.escape === "function" ? CSS.escape(coord) : coord;
}

/** Clicks on package node header actions should not collapse the open palette panel. */
function isPackagePaletteDismissOutsideClick(target: EventTarget | null): boolean {
    if (!(target instanceof Element)) return true;
    if (target.closest('[data-curio-node-warehouse-drawer="true"]')) return false;
    if (target.closest('[data-curio-package-palette-node-action="true"]')) return false;
    return true;
}

export const PackagesPaletteDropdown = memo(function PackagesPaletteDropdown({ groups }: { groups: PackagePaletteGroup[] }) {
    const [open, setOpen] = useState(false);
    const rootRef = useRef<HTMLDivElement>(null);
    const packagePaletteScrollRef = useRef<HTMLDivElement>(null);
    const { openNodeWarehouseDrawer } = useNodeWarehouseDrawer();
    const { showToast } = useToastContext();
    const { getStarters } = useStarterContext();
    const {
        activePackageKey,
        setActivePackageKey,
        paletteDockRevealCoord,
        setPaletteDockRevealCoord,
    } = usePackagePalette();

    const [forkManualPickByRoot, setForkManualPickByRoot] = useState<Record<string, string>>({});
    const [paletteCatalogSnapshot, setPaletteCatalogSnapshot] = useState<{
        publishedDirNames: Set<string>;
        installedByDir: Map<string, PackagePayload>;
        publishAllowed: boolean;
    } | null>(null);
    const [publishingPackageKey, setPublishingPackageKey] = useState<string | null>(null);
    const paletteCatalogRef = useRef(paletteCatalogSnapshot);
    paletteCatalogRef.current = paletteCatalogSnapshot;
    const paletteRows = useMemo(
        () => partitionPalettePackageGroups(groups),
        [groups],
    );

    const close = useCallback(() => setOpen(false), []);

    const prevPaletteOpenRef = useRef(false);
    useEffect(() => {
        if (prevPaletteOpenRef.current && !open) {
            setPaletteDockRevealCoord(null);
        }
        prevPaletteOpenRef.current = open;
    }, [open, setPaletteDockRevealCoord]);
    const toggle = useCallback(() => setOpen((v) => !v), []);

    const packageRegistryBootstrapKey = useSyncExternalStore(
        subscribeToRegistry,
        paletteDescriptorBootstrapKey,
        () => "ssr",
    );

    useEffect(() => {
        if (!open) return;
        const onKey = (ev: KeyboardEvent) => {
            if (ev.key === "Escape") close();
        };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, [open, close]);

    useEffect(() => {
        if (!open) return;
        const onDocMouseDown = (ev: MouseEvent) => {
            if (rootRef.current?.contains(ev.target as Node)) return;
            if (!isPackagePaletteDismissOutsideClick(ev.target)) return;
            close();
        };
        document.addEventListener("mousedown", onDocMouseDown, true);
        return () => document.removeEventListener("mousedown", onDocMouseDown, true);
    }, [open, close]);

    useEffect(() => {
        if (!open) return;
        let cancelled = false;
        void (async () => {
            try {
                const [cat, cap, installed] = await Promise.all([
                    packagesApi.catalog(),
                    packagesApi.factoryCapabilities(),
                    packagesApi.listInstalled(),
                ]);
                if (cancelled) return;
                setPaletteCatalogSnapshot({
                    publishedDirNames: new Set(cat.packages.map((p) => p.dirName)),
                    installedByDir: new Map(installed.packages.map((p) => [p.dirName, p])),
                    publishAllowed: cap.catalogPublish,
                });
            } catch (err) {
                if (cancelled) return;
                setPaletteCatalogSnapshot({
                    publishedDirNames: new Set(),
                    installedByDir: new Map(),
                    publishAllowed: true,
                });
                showToast((err as Error)?.message ?? "Could not load catalog metadata.", "warning");
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [open, showToast, packageRegistryBootstrapKey]);

    useEffect(() => {
        if (paletteDockRevealCoord?.trim()) setOpen(true);
    }, [paletteDockRevealCoord]);

    useEffect(() => {
        const coord = paletteDockRevealCoord?.trim();
        if (!open || !coord) return undefined;

        const scrollEl = packagePaletteScrollRef.current;
        let cancelled = false;
        let attempts = 0;
        const maxAttempts = 48;

        const tryReveal = (): void => {
            if (cancelled || !scrollEl) return;
            const sel = `:scope > [data-package-palette-coords~="${escapeCssAttrToken(coord)}"]`;
            const anchor = scrollEl.querySelector<HTMLElement>(sel);
            attempts++;
            if (!anchor?.isConnected || !scrollEl.contains(anchor)) {
                if (attempts < maxAttempts) requestAnimationFrame(tryReveal);
                else setPaletteDockRevealCoord(null);
                return;
            }
            anchor.scrollIntoView({ behavior: "smooth", block: "start", inline: "nearest" });
            const details = anchor.querySelector("details");
            if (details) details.open = true;
            setPaletteDockRevealCoord(null);
        };

        const id = window.requestAnimationFrame(tryReveal);
        return () => {
            cancelled = true;
            window.cancelAnimationFrame(id);
        };
    }, [
        open,
        packageRegistryBootstrapKey,
        paletteDockRevealCoord,
        paletteRows,
        setPaletteDockRevealCoord,
    ]);

    const onPublishToCatalog = useCallback(
        async (dirName: string) => {
            const row = paletteCatalogRef.current?.installedByDir.get(dirName);
            if (!row) {
                showToast("Package metadata not loaded yet.", "warning");
                return;
            }
            setPublishingPackageKey(dirName);
            try {
                const draft = draftFromInstalledPackagePayload(row, getStarters);
                await packagesApi.factoryPublishCatalog({
                    ...(toApiPayload(draft) as Record<string, unknown>),
                    replace: true,
                });
                setPaletteCatalogSnapshot((prev) => {
                    if (!prev) return prev;
                    const nextPublished = new Set(prev.publishedDirNames);
                    nextPublished.add(dirName);
                    return { ...prev, publishedDirNames: nextPublished };
                });
                showToast(`Published ${dirName} to dev catalog fixtures.`, "success");
            } catch (e) {
                showToast((e as Error)?.message ?? "Publish failed.", "error");
            } finally {
                setPublishingPackageKey(null);
            }
        },
        [getStarters, showToast],
    );

    const totalPackagesDisplayed = useMemo(
        () => visiblePaletteTriggerPackagesCount({ paletteRows }),
        [paletteRows],
    );

    return (
        <div id="packages-palette" className={packageStyles.packagePaletteRoot} ref={rootRef}>
            <div className={packageStyles.packagePaletteColumn}>
                <button
                    type="button"
                    className={`${packageStyles.packagePaletteTrigger} ${open ? packageStyles.packagePaletteTriggerOpen : ""}`}
                    onClick={toggle}
                    aria-expanded={open}
                    aria-haspopup="true"
                    title={open ? "Close package nodes" : "Open package nodes"}
                >
                    <FontAwesomeIcon icon={faCube} className={packageStyles.packagePaletteTriggerIcon} />
                    <span className={packageStyles.packagePaletteTriggerLabel}>Packages</span>
                    <span className={packageStyles.packagePaletteTriggerCount}>{totalPackagesDisplayed}</span>
                    <FontAwesomeIcon icon={open ? faChevronUp : faChevronDown} className={packageStyles.packagePaletteTriggerChevron} />
                </button>
                {paletteRows.length === 0 ? (
                    <p className={packageStyles.packagePaletteEmptyHint}>No packages yet</p>
                ) : null}
            </div>
            {open && (
                <div className={packageStyles.packagePalettePanel} role="region" aria-label="Package templates">
                    <div className={packageStyles.packagePaletteToolbar}>
                        <div className={packageStyles.packagePalettePanelTitle}>NODE PACKAGES</div>
                    </div>
                    <div ref={packagePaletteScrollRef} className={packageStyles.packagePaletteScroll}>
                        {paletteRows.map((row) =>
                            row.kind === "singleton" ? (
                                <div
                                    key={row.group.key}
                                    className={packageStyles.packagePaletteRowAnchor}
                                    data-pkg-palette-coords={row.group.key}
                                >
                                    <InstalledPackageAccordion
                                        group={row.group}
                                        activePackageKey={activePackageKey}
                                        setActivePackageKey={setActivePackageKey}
                                        catalogMetadataLoaded={paletteCatalogSnapshot !== null}
                                        catalogPublishAllowed={paletteCatalogSnapshot?.publishAllowed ?? true}
                                        isCatalogPublished={
                                            paletteCatalogSnapshot?.publishedDirNames.has(row.group.key) ?? false
                                        }
                                        publishingPackageKey={publishingPackageKey}
                                        onPublishToCatalog={onPublishToCatalog}
                                    />
                                </div>
                            ) : (
                                <div
                                    key={`fork-family:${row.rootKey}`}
                                    className={packageStyles.packagePaletteRowAnchor}
                                    data-pkg-palette-coords={row.members.map((m) => m.key).join(" ")}
                                >
                                    <PaletteForkFamily
                                        rootKey={row.rootKey}
                                        members={row.members}
                                        activePackageKey={activePackageKey}
                                        setActivePackageKey={setActivePackageKey}
                                        forkManualPickByRoot={forkManualPickByRoot}
                                        setForkManualPickByRoot={setForkManualPickByRoot}
                                        catalogMetadataLoaded={paletteCatalogSnapshot !== null}
                                        catalogPublishAllowed={paletteCatalogSnapshot?.publishAllowed ?? true}
                                        publishingPackageKey={publishingPackageKey}
                                        catalogPublishedDirNames={paletteCatalogSnapshot?.publishedDirNames ?? null}
                                        onPublishToCatalog={onPublishToCatalog}
                                    />
                                </div>
                            ),
                        )}
                    </div>
                    <div className={packageStyles.packagePaletteFooter}>
                        <button
                            type="button"
                            className={packageStyles.packageGetPackagesBtn}
                            title="Browse and install node packages"
                            aria-label="Get more packages — open node warehouse drawer"
                            onClick={() => {
                                openNodeWarehouseDrawer();
                            }}
                        >
                            Get more packages +
                        </button>
                    </div>
                </div>
            )}
        </div>
    );
});

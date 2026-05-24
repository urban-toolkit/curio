import React, { memo, useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import {
    faChevronDown,
    faChevronUp,
    faCirclePlus,
    faCube,
} from "@fortawesome/free-solid-svg-icons";
import { useReactFlow } from "reactflow";
import { packagesApi, refreshPackageRegistry } from "../../../../api/packagesApi";
import type { InstallResponse, PackagePayload } from "../../../../api/packagesApi";
import { subscribeToRegistry } from "../../../../registry";
import { draftPackageSectionKey, usePackagePalette } from "../../../../providers/PackagePaletteContext";
import { useNodeFactoryModal } from "../../../../providers/NodeFactoryModalProvider";
import { useNodeWarehouseDrawer } from "../../../../providers/NodeWarehouseDrawerProvider";
import { useToastContext } from "../../../../providers/ToastProvider";
import { useTemplateContext } from "../../../../providers/TemplateProvider";
import {
    buildDraftForPaletteSection,
    buildFactoryInstallEnvelope,
    draftForkFromInstalledPackagePayload,
    draftFromInstalledPackagePayload,
} from "../../../../utils/palettePackageFactoryDraft";
import { toApiPayload } from "../../../../pages/nodes/factoryDraftModel";
import { partitionPalettePackageGroups } from "../../../../utils/forkPackageLineage";
import { InstalledPackageAccordion } from "./InstalledPackageAccordion";
import { PaletteForkFamily } from "./PaletteForkFamily";
import { visiblePaletteTriggerPackagesCount, type PackagePaletteGroup } from "./model";
import { PackageCanvasDropSlot, PackageStagedCanvasRow } from "./PackagePaletteRows";
import { paletteDescriptorBootstrapKey } from "./registryBootstrap";
import packageStyles from "./ToolsMenuPackagePalette.module.css";

function escapeCssAttrToken(coord: string): string {
    return typeof CSS !== "undefined" && typeof CSS.escape === "function" ? CSS.escape(coord) : coord;
}

/** Clicks on package node header actions should not collapse the open palette panel. */
function isPackagePaletteDismissOutsideClick(target: EventTarget | null): boolean {
    if (!(target instanceof Element)) return true;
    if (target.closest('[data-curio-node-factory-overlay="true"]')) return false;
    if (target.closest('[data-curio-node-warehouse-drawer="true"]')) return false;
    if (target.closest('[data-curio-package-palette-node-action="true"]')) return false;
    return true;
}

export const PackagesPaletteDropdown = memo(function PackagesPaletteDropdown({ groups }: { groups: PackagePaletteGroup[] }) {
    const [open, setOpen] = useState(false);
    const [savingDraft, setSavingDraft] = useState(false);
    const rootRef = useRef<HTMLDivElement>(null);
    const packagePaletteScrollRef = useRef<HTMLDivElement>(null);
    const { openNodeFactory } = useNodeFactoryModal();
    const { openNodeWarehouseDrawer } = useNodeWarehouseDrawer();
    const { showToast } = useToastContext();
    const { getTemplates } = useTemplateContext();
    const { getNodes } = useReactFlow();
    const {
        activePackageKey,
        setActivePackageKey,
        packagesPaletteEditMode,
        setPackagesPaletteEditMode,
        paletteDockRevealCoord,
        setPaletteDockRevealCoord,
        draftPackageSectionIds,
        registerDraftPackageSection,
        stagedRowsByPackageKey,
        removedKindIdsByPackageKey,
    } = usePackagePalette();

    const onPackageInstalledFocusDock = useCallback(
        (pkg: Pick<PackagePayload, "packageId" | "major">) => {
            const coord = `${pkg.packageId}@${pkg.major}`;
            setPaletteDockRevealCoord(coord);
            setActivePackageKey(coord);
        },
        [setActivePackageKey, setPaletteDockRevealCoord],
    );

    const onFactoryModalInstallSuccess = useCallback(
        (result: InstallResponse) => {
            onPackageInstalledFocusDock(result.package);
        },
        [onPackageInstalledFocusDock],
    );

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
            if (ev.key === "Escape") {
                if (packagesPaletteEditMode) setPackagesPaletteEditMode(false);
                else close();
            }
        };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, [open, close, packagesPaletteEditMode, setPackagesPaletteEditMode]);

    useEffect(() => {
        if (!open || packagesPaletteEditMode) return;
        const onDocMouseDown = (ev: MouseEvent) => {
            if (rootRef.current?.contains(ev.target as Node)) return;
            if (!isPackagePaletteDismissOutsideClick(ev.target)) return;
            close();
        };
        document.addEventListener("mousedown", onDocMouseDown, true);
        return () => document.removeEventListener("mousedown", onDocMouseDown, true);
    }, [open, close, packagesPaletteEditMode]);

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

    const openWizardForPaletteSection = useCallback(
        (sectionKey: string, opts: { group?: PackagePaletteGroup; draftUuid?: string }) => {
            const stagedRows = [...(stagedRowsByPackageKey[sectionKey] ?? [])];
            const removedKindIds = [...(removedKindIdsByPackageKey[sectionKey] ?? [])];
            const hasPendingEdits = stagedRows.length > 0 || removedKindIds.length > 0;

            if (!hasPendingEdits && opts.group && packagesPaletteEditMode) {
                const row = paletteCatalogRef.current?.installedByDir.get(sectionKey);
                if (row) {
                    openNodeFactory({
                        draft: draftForkFromInstalledPackagePayload(row, getTemplates),
                        forkInstallNotice: true,
                        onInstallSuccess: onFactoryModalInstallSuccess,
                    });
                    return;
                }
                void (async () => {
                    try {
                        const { packages } = await packagesApi.listInstalled();
                        const found = packages.find((p) => p.dirName === sectionKey);
                        if (!found) {
                            showToast(
                                "Could not load metadata for this package. Check that it is installed, then try again.",
                                "warning",
                            );
                            return;
                        }
                        setPaletteCatalogSnapshot((prev) => {
                            const installedByDir = new Map(prev?.installedByDir ?? []);
                            installedByDir.set(sectionKey, found);
                            return {
                                publishedDirNames: prev?.publishedDirNames ?? new Set(),
                                publishAllowed: prev?.publishAllowed ?? true,
                                installedByDir,
                            };
                        });
                        openNodeFactory({
                            draft: draftForkFromInstalledPackagePayload(found, getTemplates),
                            forkInstallNotice: true,
                            onInstallSuccess: onFactoryModalInstallSuccess,
                        });
                    } catch (e) {
                        showToast(
                            (e as Error)?.message ?? "Could not load installed package metadata.",
                            "warning",
                        );
                    }
                })();
                return;
            }

            if (!hasPendingEdits) {
                showToast(
                    "Stage a canvas node or remove a package kind first (edit mode).",
                    "warning",
                );
                return;
            }
            const nodes = getNodes();
            const draft =
                opts.group != null
                    ? buildDraftForPaletteSection({
                          sectionKey,
                          stagedRows,
                          rfNodes: nodes,
                          group: opts.group,
                          palettePackageGroups: groups,
                          getTemplates,
                          removedKindIds,
                      })
                    : buildDraftForPaletteSection({
                          sectionKey,
                          stagedRows,
                          rfNodes: nodes,
                          standaloneDraft: true,
                          standalonePackageLeaf: opts.draftUuid ?? sectionKey.replace(/^__draft__:/, ""),
                          palettePackageGroups: groups,
                          getTemplates,
                          removedKindIds,
                      });
            if (!draft) {
                showToast("Could not derive a factory draft from the staged nodes.", "error");
                return;
            }
            openNodeFactory({ draft, onInstallSuccess: onFactoryModalInstallSuccess });
        },
        [
            getNodes,
            getTemplates,
            groups,
            onFactoryModalInstallSuccess,
            openNodeFactory,
            packagesPaletteEditMode,
            removedKindIdsByPackageKey,
            showToast,
            stagedRowsByPackageKey,
        ],
    );

    const onPublishToCatalog = useCallback(
        async (dirName: string) => {
            const row = paletteCatalogRef.current?.installedByDir.get(dirName);
            if (!row) {
                showToast("Package metadata not loaded yet.", "warning");
                return;
            }
            setPublishingPackageKey(dirName);
            try {
                const draft = draftFromInstalledPackagePayload(row, getTemplates);
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
        [getTemplates, showToast],
    );

    const onConfirmSaveDrafts = useCallback(async () => {
        if (savingDraft) return;
        setSavingDraft(true);
        try {
            const nodes = getNodes();
            let installs = 0;
            let skippedSections = 0;
            let lastInstalledCoord: string | null = null;

            for (const draftId of draftPackageSectionIds) {
                const sectionKey = draftPackageSectionKey(draftId);
                const stagedRows = [...(stagedRowsByPackageKey[sectionKey] ?? [])];
                const removedKindIds = [...(removedKindIdsByPackageKey[sectionKey] ?? [])];
                if (!stagedRows.length && !removedKindIds.length) {
                    skippedSections++;
                    continue;
                }
                const draft = buildDraftForPaletteSection({
                    sectionKey,
                    stagedRows,
                    rfNodes: nodes,
                    standaloneDraft: true,
                    standalonePackageLeaf: draftId,
                    palettePackageGroups: groups,
                    getTemplates,
                    removedKindIds,
                });
                if (!draft) {
                    skippedSections++;
                    continue;
                }
                const coord = `${draft.packageId}@${draft.major}`;
                const overwriteInstalledPackagePalette = groups.some((g) => g.key === coord);
                await packagesApi.factoryInstall(buildFactoryInstallEnvelope(draft, overwriteInstalledPackagePalette));
                lastInstalledCoord = coord;
                installs++;
            }

            for (const group of groups) {
                const stagedRows = [...(stagedRowsByPackageKey[group.key] ?? [])];
                const removedKindIds = [...(removedKindIdsByPackageKey[group.key] ?? [])];
                if (!stagedRows.length && !removedKindIds.length) continue;
                const draft = buildDraftForPaletteSection({
                    sectionKey: group.key,
                    stagedRows,
                    rfNodes: nodes,
                    group,
                    palettePackageGroups: groups,
                    getTemplates,
                    removedKindIds,
                });
                if (!draft) {
                    skippedSections++;
                    continue;
                }
                const coordAfter = `${draft.packageId}@${draft.major}`;
                await packagesApi.factoryInstall(buildFactoryInstallEnvelope(draft, false));
                lastInstalledCoord = coordAfter;
                installs++;
            }

            if (!installs) {
                showToast(
                    "Nothing new to save — stage canvas nodes, remove package kinds, or both.",
                    "info",
                );
                return;
            }

            await refreshPackageRegistry();

            if (lastInstalledCoord != null) {
                setPaletteDockRevealCoord(lastInstalledCoord);
                setActivePackageKey(lastInstalledCoord);
            }

            showToast(
                skippedSections > 0
                    ? `Installed ${installs} palette package(s); some sections had nothing staged.`
                    : `Installed ${installs} palette package(s).`,
                "success",
            );
            setPackagesPaletteEditMode(false);
        } catch (e) {
            showToast((e as Error)?.message ?? "Saving palette packages failed.", "error");
        } finally {
            setSavingDraft(false);
        }
    }, [
        draftPackageSectionIds,
        getNodes,
        getTemplates,
        groups,
        savingDraft,
        setActivePackageKey,
        setPackagesPaletteEditMode,
        setPaletteDockRevealCoord,
        showToast,
        removedKindIdsByPackageKey,
        stagedRowsByPackageKey,
    ]);

    const onCancelEdit = useCallback(() => {
        setPackagesPaletteEditMode(false);
    }, [setPackagesPaletteEditMode]);

    const totalPackagesDisplayed = useMemo(
        () =>
            visiblePaletteTriggerPackagesCount({
                paletteRows,
                packagesPaletteEditMode,
                draftPackageSectionIds,
            }),
        [paletteRows, packagesPaletteEditMode, draftPackageSectionIds],
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
                {!packagesPaletteEditMode && paletteRows.length === 0 ? (
                    <p className={packageStyles.packagePaletteEmptyHint}>No packages yet</p>
                ) : null}
            </div>
            {open && (
                <div className={packageStyles.packagePalettePanel} role="region" aria-label="Package node kinds">
                    <div className={packageStyles.packagePaletteToolbar}>
                        <div className={packageStyles.packagePalettePanelTitle}>NODE PACKAGES</div>
                        {!packagesPaletteEditMode ? (
                            <button
                                type="button"
                                className={packageStyles.packageEditToggle}
                                onClick={() => setPackagesPaletteEditMode(true)}
                            >
                                Edit
                            </button>
                        ) : (
                            <>
                                <button
                                    type="button"
                                    className={packageStyles.packageToolbarBtnPrimary}
                                    disabled={savingDraft}
                                    title={
                                        savingDraft
                                            ? undefined
                                            : "Writes merged kinds into installed packages under Packages palette. Existing nodes on the canvas are left unchanged."
                                    }
                                    onClick={() => void onConfirmSaveDrafts()}
                                >
                                    {savingDraft ? "Saving…" : "Save draft"}
                                </button>
                                <button type="button" className={packageStyles.packageToolbarBtn} onClick={onCancelEdit}>
                                    Cancel
                                </button>
                            </>
                        )}
                    </div>
                    <div ref={packagePaletteScrollRef} className={packageStyles.packagePaletteScroll}>
                        {packagesPaletteEditMode ? (
                            <button
                                type="button"
                                className={packageStyles.packageAddSectionRow}
                                onClick={() => registerDraftPackageSection()}
                            >
                                <FontAwesomeIcon icon={faCirclePlus} className={packageStyles.packageAddSectionIcon} aria-hidden />
                                <span>Add new pkg</span>
                            </button>
                        ) : null}
                        {packagesPaletteEditMode
                            ? draftPackageSectionIds.map((draftId) => {
                                  const sectionKey = draftPackageSectionKey(draftId);
                                  const stagedRows = stagedRowsByPackageKey[sectionKey] ?? [];
                                  return (
                                      <details
                                          key={sectionKey}
                                          className={`${packageStyles.packageDetails} ${sectionKey === activePackageKey ? packageStyles.packageDetailsSelected : ""}`}
                                      >
                                          <summary
                                              className={packageStyles.packageSummary}
                                              onClick={() => setActivePackageKey(sectionKey)}
                                          >
                                              <div className={packageStyles.packageSummaryRow}>
                                                  <span
                                                      className={packageStyles.packageSummaryTitle}
                                                      role={packagesPaletteEditMode && stagedRows.length > 0 ? "button" : undefined}
                                                      title={
                                                          packagesPaletteEditMode && stagedRows.length > 0
                                                              ? "Open Node Factory with this draft"
                                                              : undefined
                                                      }
                                                      onClick={(e) => {
                                                          if (!(packagesPaletteEditMode && stagedRows.length > 0)) return;
                                                          e.preventDefault();
                                                          e.stopPropagation();
                                                          setActivePackageKey(sectionKey);
                                                          openWizardForPaletteSection(sectionKey, { draftUuid: draftId });
                                                      }}
                                                  >
                                                      New pkg (draft)
                                                  </span>
                                                  <span className={packageStyles.packageSummaryCount}>{stagedRows.length}</span>
                                              </div>
                                          </summary>
                                          <div className={packageStyles.packageKindGrid}>
                                              {stagedRows.map((row) => (
                                                  <PackageStagedCanvasRow
                                                      key={row.rowId}
                                                      packageSectionKey={sectionKey}
                                                      rowId={row.rowId}
                                                      canvasNodeId={row.canvasNodeId}
                                                  />
                                              ))}
                                              <PackageCanvasDropSlot packageSectionKey={sectionKey} />
                                          </div>
                                      </details>
                                  );
                              })
                            : null}
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
                                        packagesPaletteEditMode={packagesPaletteEditMode}
                                        stagedInstalledRows={stagedRowsByPackageKey[row.group.key] ?? []}
                                        openWizardForPaletteSection={openWizardForPaletteSection}
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
                                        packagesPaletteEditMode={packagesPaletteEditMode}
                                        stagedRowsByPackageKey={stagedRowsByPackageKey}
                                        removedKindIdsByPackageKey={removedKindIdsByPackageKey}
                                        forkManualPickByRoot={forkManualPickByRoot}
                                        setForkManualPickByRoot={setForkManualPickByRoot}
                                        openWizardForPaletteSection={openWizardForPaletteSection}
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

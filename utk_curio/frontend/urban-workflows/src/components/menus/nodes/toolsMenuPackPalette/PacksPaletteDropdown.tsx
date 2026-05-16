import React, { memo, useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import {
    faChevronDown,
    faChevronUp,
    faCirclePlus,
    faCube,
} from "@fortawesome/free-solid-svg-icons";
import { useReactFlow } from "reactflow";
import { packsApi, refreshPackRegistry } from "../../../../api/packsApi";
import type { PackPayload } from "../../../../api/packsApi";
import { subscribeToRegistry } from "../../../../registry";
import { draftPackSectionKey, usePackPalette } from "../../../../providers/PackPaletteContext";
import { useNodeFactoryModal } from "../../../../providers/NodeFactoryModalProvider";
import { useToastContext } from "../../../../providers/ToastProvider";
import { useTemplateContext } from "../../../../providers/TemplateProvider";
import {
    buildDraftForPaletteSection,
    buildFactoryInstallEnvelope,
    draftForkFromInstalledPackPayload,
    draftFromInstalledPackPayload,
} from "../../../../utils/palettePackFactoryDraft";
import { toApiPayload } from "../../../../pages/nodes/factoryDraftModel";
import {
    filterForkParentHiddenPalettePackGroups,
    partitionPalettePackGroups,
} from "../../../../utils/forkPackLineage";
import { InstalledPackAccordion } from "./InstalledPackAccordion";
import { PaletteForkFamily } from "./PaletteForkFamily";
import {
    visiblePaletteTriggerKindsCount,
    type PackPaletteGroup,
} from "./model";
import { PackCanvasDropSlot, PackStagedCanvasRow } from "./PackPaletteRows";
import { paletteDescriptorBootstrapKey } from "./registryBootstrap";
import packStyles from "./ToolsMenuPackPalette.module.css";

export const PacksPaletteDropdown = memo(function PacksPaletteDropdown({ groups }: { groups: PackPaletteGroup[] }) {
    const [open, setOpen] = useState(false);
    const [savingDraft, setSavingDraft] = useState(false);
    const rootRef = useRef<HTMLDivElement>(null);
    const { openNodeFactory } = useNodeFactoryModal();
    const { showToast } = useToastContext();
    const { getTemplates } = useTemplateContext();
    const { getNodes } = useReactFlow();
    const {
        activePackKey,
        setActivePackKey,
        packsPaletteEditMode,
        setPacksPaletteEditMode,
        draftPackSectionIds,
        registerDraftPackSection,
        stagedRowsByPackKey,
    } = usePackPalette();

    const [forkManualPickByRoot, setForkManualPickByRoot] = useState<Record<string, string>>({});
    const [paletteCatalogSnapshot, setPaletteCatalogSnapshot] = useState<{
        publishedDirNames: Set<string>;
        installedByDir: Map<string, PackPayload>;
        publishAllowed: boolean;
    } | null>(null);
    const [publishingPackKey, setPublishingPackKey] = useState<string | null>(null);
    const paletteCatalogRef = useRef(paletteCatalogSnapshot);
    paletteCatalogRef.current = paletteCatalogSnapshot;
    const paletteRows = useMemo(
        () => partitionPalettePackGroups(filterForkParentHiddenPalettePackGroups(groups)),
        [groups],
    );

    const close = useCallback(() => setOpen(false), []);
    const toggle = useCallback(() => setOpen((v) => !v), []);

    const packRegistryBootstrapKey = useSyncExternalStore(
        subscribeToRegistry,
        paletteDescriptorBootstrapKey,
        () => "ssr",
    );

    useEffect(() => {
        if (!open) return;
        const onKey = (ev: KeyboardEvent) => {
            if (ev.key === "Escape") {
                if (packsPaletteEditMode) setPacksPaletteEditMode(false);
                else close();
            }
        };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, [open, close, packsPaletteEditMode, setPacksPaletteEditMode]);

    useEffect(() => {
        if (!open || packsPaletteEditMode) return;
        const onDocMouseDown = (ev: MouseEvent) => {
            if (rootRef.current?.contains(ev.target as Node)) return;
            close();
        };
        document.addEventListener("mousedown", onDocMouseDown, true);
        return () => document.removeEventListener("mousedown", onDocMouseDown, true);
    }, [open, close, packsPaletteEditMode]);

    useEffect(() => {
        if (!open) return;
        let cancelled = false;
        void (async () => {
            try {
                const [cat, cap, installed] = await Promise.all([
                    packsApi.catalog(),
                    packsApi.factoryCapabilities(),
                    packsApi.listInstalled(),
                ]);
                if (cancelled) return;
                setPaletteCatalogSnapshot({
                    publishedDirNames: new Set(cat.packs.map((p) => p.dirName)),
                    installedByDir: new Map(installed.packs.map((p) => [p.dirName, p])),
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
    }, [open, showToast, packRegistryBootstrapKey]);

    const openWizardForPaletteSection = useCallback(
        (sectionKey: string, opts: { group?: PackPaletteGroup; draftUuid?: string }) => {
            const stagedRows = [...(stagedRowsByPackKey[sectionKey] ?? [])];

            if (!stagedRows.length && opts.group && packsPaletteEditMode) {
                const row = paletteCatalogRef.current?.installedByDir.get(sectionKey);
                if (row) {
                    openNodeFactory({
                        draft: draftForkFromInstalledPackPayload(row, getTemplates),
                        forkInstallNotice: true,
                    });
                    return;
                }
                void (async () => {
                    try {
                        const { packs } = await packsApi.listInstalled();
                        const found = packs.find((p) => p.dirName === sectionKey);
                        if (!found) {
                            showToast(
                                "Could not load metadata for this pack. Check that it is installed, then try again.",
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
                            draft: draftForkFromInstalledPackPayload(found, getTemplates),
                            forkInstallNotice: true,
                        });
                    } catch (e) {
                        showToast(
                            (e as Error)?.message ?? "Could not load installed pack metadata.",
                            "warning",
                        );
                    }
                })();
                return;
            }

            if (!stagedRows.length) {
                showToast(
                    "Stage at least one canvas node first (drag the grip onto the dashed drop zone).",
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
                          palettePackGroups: groups,
                          getTemplates,
                      })
                    : buildDraftForPaletteSection({
                          sectionKey,
                          stagedRows,
                          rfNodes: nodes,
                          standaloneDraft: true,
                          standalonePackLeaf: opts.draftUuid ?? sectionKey.replace(/^__draft__:/, ""),
                          palettePackGroups: groups,
                          getTemplates,
                      });
            if (!draft) {
                showToast("Could not derive a factory draft from the staged nodes.", "error");
                return;
            }
            openNodeFactory({ draft });
        },
        [
            getNodes,
            getTemplates,
            groups,
            openNodeFactory,
            packsPaletteEditMode,
            showToast,
            stagedRowsByPackKey,
        ],
    );

    const onPublishToCatalog = useCallback(
        async (dirName: string) => {
            const row = paletteCatalogRef.current?.installedByDir.get(dirName);
            if (!row) {
                showToast("Pack metadata not loaded yet.", "warning");
                return;
            }
            setPublishingPackKey(dirName);
            try {
                const draft = draftFromInstalledPackPayload(row, getTemplates);
                await packsApi.factoryPublishCatalog({
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
                setPublishingPackKey(null);
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

            for (const draftId of draftPackSectionIds) {
                const sectionKey = draftPackSectionKey(draftId);
                const stagedRows = [...(stagedRowsByPackKey[sectionKey] ?? [])];
                if (!stagedRows.length) {
                    skippedSections++;
                    continue;
                }
                const draft = buildDraftForPaletteSection({
                    sectionKey,
                    stagedRows,
                    rfNodes: nodes,
                    standaloneDraft: true,
                    standalonePackLeaf: draftId,
                    palettePackGroups: groups,
                    getTemplates,
                });
                if (!draft) {
                    skippedSections++;
                    continue;
                }
                const coord = `${draft.packId}@${draft.major}`;
                const overwriteInstalledPackPalette = groups.some((g) => g.key === coord);
                await packsApi.factoryInstall(buildFactoryInstallEnvelope(draft, overwriteInstalledPackPalette));
                installs++;
            }

            for (const group of groups) {
                const stagedRows = [...(stagedRowsByPackKey[group.key] ?? [])];
                if (!stagedRows.length) continue;
                const draft = buildDraftForPaletteSection({
                    sectionKey: group.key,
                    stagedRows,
                    rfNodes: nodes,
                    group,
                    palettePackGroups: groups,
                    getTemplates,
                });
                if (!draft) {
                    skippedSections++;
                    continue;
                }
                await packsApi.factoryInstall(buildFactoryInstallEnvelope(draft, false));
                installs++;
            }

            if (!installs) {
                showToast("Nothing new to save — stage canvas nodes onto a draft or pack section first.", "info");
                return;
            }

            await refreshPackRegistry();

            showToast(
                skippedSections > 0
                    ? `Installed ${installs} palette pack(s); some sections had nothing staged.`
                    : `Installed ${installs} palette pack(s).`,
                "success",
            );
            setPacksPaletteEditMode(false);
        } catch (e) {
            showToast((e as Error)?.message ?? "Saving palette packs failed.", "error");
        } finally {
            setSavingDraft(false);
        }
    }, [
        draftPackSectionIds,
        getNodes,
        getTemplates,
        groups,
        savingDraft,
        setPacksPaletteEditMode,
        showToast,
        stagedRowsByPackKey,
    ]);

    const onCancelEdit = useCallback(() => {
        setPacksPaletteEditMode(false);
    }, [setPacksPaletteEditMode]);

    const totalKindsDisplayed = useMemo(
        () =>
            visiblePaletteTriggerKindsCount({
                paletteRows,
                packsPaletteEditMode,
                stagedRowsByPackKey,
                draftPackSectionIds,
                activePackKey,
                forkManualPickByRoot,
            }),
        [
            paletteRows,
            packsPaletteEditMode,
            stagedRowsByPackKey,
            draftPackSectionIds,
            activePackKey,
            forkManualPickByRoot,
        ],
    );

    return (
        <div id="packs-palette" className={packStyles.packPaletteRoot} ref={rootRef}>
            <button
                type="button"
                className={`${packStyles.packPaletteTrigger} ${open ? packStyles.packPaletteTriggerOpen : ""}`}
                onClick={toggle}
                aria-expanded={open}
                aria-haspopup="true"
                title={open ? "Close pack nodes" : "Open pack nodes"}
            >
                <FontAwesomeIcon icon={faCube} className={packStyles.packPaletteTriggerIcon} />
                <span className={packStyles.packPaletteTriggerLabel}>Packs</span>
                <span className={packStyles.packPaletteTriggerCount}>{totalKindsDisplayed}</span>
                <FontAwesomeIcon icon={open ? faChevronUp : faChevronDown} className={packStyles.packPaletteTriggerChevron} />
            </button>
            {open && (
                <div className={packStyles.packPalettePanel} role="region" aria-label="Pack node kinds">
                    <div className={packStyles.packPaletteToolbar}>
                        {!packsPaletteEditMode ? (
                            <button
                                type="button"
                                className={packStyles.packEditToggle}
                                onClick={() => setPacksPaletteEditMode(true)}
                            >
                                Edit
                            </button>
                        ) : (
                            <>
                                <button
                                    type="button"
                                    className={packStyles.packToolbarBtnPrimary}
                                    disabled={savingDraft}
                                    title={
                                        savingDraft
                                            ? undefined
                                            : "Writes merged kinds into installed packs under Packs palette. Existing nodes on the canvas are left unchanged."
                                    }
                                    onClick={() => void onConfirmSaveDrafts()}
                                >
                                    {savingDraft ? "Saving…" : "Save draft"}
                                </button>
                                <button type="button" className={packStyles.packToolbarBtn} onClick={onCancelEdit}>
                                    Cancel
                                </button>
                            </>
                        )}
                    </div>
                    <div className={packStyles.packPalettePanelTitle}>Nodes by pack</div>
                    <div className={packStyles.packPaletteScroll}>
                        {packsPaletteEditMode ? (
                            <button
                                type="button"
                                className={packStyles.packAddSectionRow}
                                onClick={() => registerDraftPackSection()}
                            >
                                <FontAwesomeIcon icon={faCirclePlus} className={packStyles.packAddSectionIcon} aria-hidden />
                                <span>Add new pack</span>
                            </button>
                        ) : null}
                        {packsPaletteEditMode
                            ? draftPackSectionIds.map((draftId) => {
                                  const sectionKey = draftPackSectionKey(draftId);
                                  const stagedRows = stagedRowsByPackKey[sectionKey] ?? [];
                                  return (
                                      <details
                                          key={sectionKey}
                                          className={`${packStyles.packDetails} ${sectionKey === activePackKey ? packStyles.packDetailsSelected : ""}`}
                                      >
                                          <summary
                                              className={packStyles.packSummary}
                                              onClick={() => setActivePackKey(sectionKey)}
                                          >
                                              <div className={packStyles.packSummaryRow}>
                                                  <span
                                                      className={packStyles.packSummaryTitle}
                                                      role={packsPaletteEditMode && stagedRows.length > 0 ? "button" : undefined}
                                                      title={
                                                          packsPaletteEditMode && stagedRows.length > 0
                                                              ? "Open Node Factory with this draft"
                                                              : undefined
                                                      }
                                                      onClick={(e) => {
                                                          if (!(packsPaletteEditMode && stagedRows.length > 0)) return;
                                                          e.preventDefault();
                                                          e.stopPropagation();
                                                          setActivePackKey(sectionKey);
                                                          openWizardForPaletteSection(sectionKey, { draftUuid: draftId });
                                                      }}
                                                  >
                                                      New pack (draft)
                                                  </span>
                                                  <span className={packStyles.packSummaryCount}>{stagedRows.length}</span>
                                              </div>
                                          </summary>
                                          <div className={packStyles.packKindGrid}>
                                              {stagedRows.map((row) => (
                                                  <PackStagedCanvasRow
                                                      key={row.rowId}
                                                      packSectionKey={sectionKey}
                                                      rowId={row.rowId}
                                                      canvasNodeId={row.canvasNodeId}
                                                  />
                                              ))}
                                              <PackCanvasDropSlot packSectionKey={sectionKey} />
                                          </div>
                                      </details>
                                  );
                              })
                            : null}
                        {paletteRows.map((row) =>
                            row.kind === "singleton" ? (
                                <InstalledPackAccordion
                                    key={row.group.key}
                                    group={row.group}
                                    activePackKey={activePackKey}
                                    setActivePackKey={setActivePackKey}
                                    packsPaletteEditMode={packsPaletteEditMode}
                                    stagedInstalledRows={stagedRowsByPackKey[row.group.key] ?? []}
                                    openWizardForPaletteSection={openWizardForPaletteSection}
                                    catalogMetadataLoaded={paletteCatalogSnapshot !== null}
                                    catalogPublishAllowed={paletteCatalogSnapshot?.publishAllowed ?? true}
                                    isCatalogPublished={
                                        paletteCatalogSnapshot?.publishedDirNames.has(row.group.key) ?? false
                                    }
                                    publishingPackKey={publishingPackKey}
                                    onPublishToCatalog={onPublishToCatalog}
                                />
                            ) : (
                                <PaletteForkFamily
                                    key={`fork-family:${row.rootKey}`}
                                    rootKey={row.rootKey}
                                    members={row.members}
                                    activePackKey={activePackKey}
                                    setActivePackKey={setActivePackKey}
                                    packsPaletteEditMode={packsPaletteEditMode}
                                    stagedRowsByPackKey={stagedRowsByPackKey}
                                    forkManualPickByRoot={forkManualPickByRoot}
                                    setForkManualPickByRoot={setForkManualPickByRoot}
                                    openWizardForPaletteSection={openWizardForPaletteSection}
                                    catalogMetadataLoaded={paletteCatalogSnapshot !== null}
                                    catalogPublishAllowed={paletteCatalogSnapshot?.publishAllowed ?? true}
                                    publishingPackKey={publishingPackKey}
                                    catalogPublishedDirNames={paletteCatalogSnapshot?.publishedDirNames ?? null}
                                    onPublishToCatalog={onPublishToCatalog}
                                />
                            ),
                        )}
                    </div>
                </div>
            )}
        </div>
    );
});

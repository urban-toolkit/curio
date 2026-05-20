import React, { memo, useCallback, useEffect, useMemo } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faPenToSquare } from "@fortawesome/free-solid-svg-icons";
import type { PackStagedRow } from "../../../../providers/PackPaletteContext";
import { CatalogPublishPill } from "../../../packs/CatalogPublishPill";
import { ForkFamilyPicker } from "../../../packs/ForkFamilyPicker";
import { FORK_SELECTION_SESSION_PREFIX, resolveForkFamilySelectionKey } from "../../../../utils/forkPackLineage";
import { type PackPaletteGroup } from "./model";
import { InstalledPackAccordion } from "./InstalledPackAccordion";
import packStyles from "./ToolsMenuPackPalette.module.css";

export interface PaletteForkFamilyProps {
    rootKey: string;
    members: PackPaletteGroup[];
    activePackKey: string | null;
    setActivePackKey: (k: string | null) => void;
    packsPaletteEditMode: boolean;
    stagedRowsByPackKey: Readonly<Record<string, readonly PackStagedRow[]>>;
    removedKindIdsByPackKey: Readonly<Record<string, readonly string[]>>;
    forkManualPickByRoot: Record<string, string>;
    setForkManualPickByRoot: React.Dispatch<React.SetStateAction<Record<string, string>>>;
    openWizardForPaletteSection: (sectionKey: string, opts: { group?: PackPaletteGroup }) => void;
    catalogMetadataLoaded: boolean;
    catalogPublishAllowed: boolean;
    publishingPackKey: string | null;
    catalogPublishedDirNames: ReadonlySet<string> | null;
    onPublishToCatalog: (dirName: string) => void;
}

export const PaletteForkFamily = memo(function PaletteForkFamily({
    rootKey,
    members,
    activePackKey,
    setActivePackKey,
    packsPaletteEditMode,
    stagedRowsByPackKey,
    removedKindIdsByPackKey,
    forkManualPickByRoot,
    setForkManualPickByRoot,
    openWizardForPaletteSection,
    catalogMetadataLoaded,
    catalogPublishAllowed,
    publishingPackKey,
    catalogPublishedDirNames,
    onPublishToCatalog,
}: PaletteForkFamilyProps) {
    const manualPick = forkManualPickByRoot[rootKey];
    const resolved = useMemo(
        () => resolveForkFamilySelectionKey(rootKey, members, activePackKey ?? "", manualPick),
        [rootKey, members, activePackKey, manualPick],
    );

    useEffect(() => {
        try {
            sessionStorage.setItem(FORK_SELECTION_SESSION_PREFIX + rootKey, resolved);
        } catch {
            /* private mode etc. */
        }
    }, [resolved, rootKey]);

    const selectedGroup = useMemo(
        () => members.find((g) => g.key === resolved) ?? members[0]!,
        [members, resolved],
    );

    const stagedInstalledRows = stagedRowsByPackKey[selectedGroup.key] ?? [];
    const removedKindIds = removedKindIdsByPackKey[selectedGroup.key] ?? [];
    const forkPublished =
        catalogPublishedDirNames != null && catalogPublishedDirNames.has(selectedGroup.key);

    const hasPendingEdits = stagedInstalledRows.length > 0 || removedKindIds.length > 0;
    const canOpenStagedFf = packsPaletteEditMode && hasPendingEdits;
    const canOpenForkFf = packsPaletteEditMode && !hasPendingEdits;
    const canOpenFactoryFf = canOpenStagedFf || canOpenForkFf;

    const onForkPickedFromPalette = useCallback(
        (next: string) => {
            setForkManualPickByRoot((prev) => ({ ...prev, [rootKey]: next }));
            setActivePackKey(next);
            try {
                sessionStorage.setItem(FORK_SELECTION_SESSION_PREFIX + rootKey, next);
            } catch {
                /* noop */
            }
        },
        [rootKey, setActivePackKey, setForkManualPickByRoot],
    );

    const forkPickerOptions = useMemo(
        () => members.map((m) => ({ key: m.key, label: m.name })),
        [members],
    );

    return (
        <div className={packStyles.packForkFamily}>
            <div className={packStyles.packForkFamilyToolbar}>
                <div className={packStyles.packForkFamilyToolbarText}>
                    <div className={packStyles.packForkFamilyTitleRow}>
                        <span
                            className={
                                canOpenFactoryFf
                                    ? `${packStyles.packForkFamilyTitle} ${packStyles.packForkFactoryTitleInteractive}`
                                    : packStyles.packForkFamilyTitle
                            }
                            role={canOpenFactoryFf ? "button" : undefined}
                            tabIndex={canOpenFactoryFf ? 0 : undefined}
                            title={
                                selectedGroup.label !== selectedGroup.name
                                    ? selectedGroup.label
                                    : canOpenStagedFf
                                      ? "Open Node Factory with staged edits"
                                      : canOpenForkFf
                                        ? "Fork this pack in Node Factory"
                                        : undefined
                            }
                            onClick={(ev) => {
                                if (!canOpenFactoryFf) return;
                                ev.preventDefault();
                                openWizardForPaletteSection(selectedGroup.key, { group: selectedGroup });
                            }}
                            onKeyDown={(ev) => {
                                if (!canOpenFactoryFf) return;
                                if (ev.key === "Enter" || ev.key === " ") {
                                    ev.preventDefault();
                                    openWizardForPaletteSection(selectedGroup.key, { group: selectedGroup });
                                }
                            }}
                        >
                            {selectedGroup.name}
                        </span>
                        {canOpenFactoryFf ? (
                            <button
                                type="button"
                                className={packStyles.packForkFamilyFactoryPen}
                                title={canOpenStagedFf ? "Open Node Factory with staged edits" : "Fork in Node Factory"}
                                aria-label={`Node Factory — ${selectedGroup.name}`}
                                onClick={(ev) => {
                                    ev.preventDefault();
                                    openWizardForPaletteSection(selectedGroup.key, { group: selectedGroup });
                                }}
                            >
                                <FontAwesomeIcon icon={faPenToSquare} />
                            </button>
                        ) : null}
                        {catalogMetadataLoaded ? (
                            <CatalogPublishPill
                                variant="dock"
                                dirName={selectedGroup.key}
                                published={forkPublished}
                                allowPublish={catalogPublishAllowed}
                                busy={publishingPackKey === selectedGroup.key}
                                onPublish={onPublishToCatalog}
                            />
                        ) : null}
                    </div>
                    <span className={packStyles.packForkFamilySubtitle} title={rootKey}>
                        Family root {rootKey} · {members.length} forks
                    </span>
                </div>
                <span className={packStyles.packSummaryCount}>{members.length}</span>
            </div>
            <ForkFamilyPicker
                variant="dock"
                rootKey={rootKey}
                options={forkPickerOptions}
                value={resolved}
                onChange={onForkPickedFromPalette}
            />
            <InstalledPackAccordion
                group={selectedGroup}
                activePackKey={activePackKey}
                setActivePackKey={setActivePackKey}
                packsPaletteEditMode={packsPaletteEditMode}
                stagedInstalledRows={stagedInstalledRows}
                openWizardForPaletteSection={openWizardForPaletteSection}
                catalogMetadataLoaded={catalogMetadataLoaded}
                catalogPublishAllowed={catalogPublishAllowed}
                isCatalogPublished={forkPublished}
                publishingPackKey={publishingPackKey}
                onPublishToCatalog={onPublishToCatalog}
                showCatalogPublishInSummary={false}
            />
        </div>
    );
});

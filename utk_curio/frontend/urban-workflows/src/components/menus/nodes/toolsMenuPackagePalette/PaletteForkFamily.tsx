import React, { memo, useCallback, useEffect, useMemo } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faPenToSquare } from "@fortawesome/free-solid-svg-icons";
import type { PackageStagedRow } from "../../../../providers/PackagePaletteContext";
import { CatalogPublishPill } from "../../../packages/CatalogPublishPill";
import { ForkFamilyPicker } from "../../../packages/ForkFamilyPicker";
import { FORK_SELECTION_SESSION_PREFIX, resolveForkFamilySelectionKey } from "../../../../utils/forkPackageLineage";
import { forkFamilyRootDisplayName, type PackagePaletteGroup } from "./model";
import { InstalledPackageAccordion } from "./InstalledPackageAccordion";
import packageStyles from "./ToolsMenuPackagePalette.module.css";

export interface PaletteForkFamilyProps {
    rootKey: string;
    members: PackagePaletteGroup[];
    activePackageKey: string | null;
    setActivePackageKey: (k: string | null) => void;
    packagesPaletteEditMode: boolean;
    stagedRowsByPackageKey: Readonly<Record<string, readonly PackageStagedRow[]>>;
    removedKindIdsByPackageKey: Readonly<Record<string, readonly string[]>>;
    forkManualPickByRoot: Record<string, string>;
    setForkManualPickByRoot: React.Dispatch<React.SetStateAction<Record<string, string>>>;
    openWizardForPaletteSection: (sectionKey: string, opts: { group?: PackagePaletteGroup }) => void;
    catalogMetadataLoaded: boolean;
    catalogPublishAllowed: boolean;
    publishingPackageKey: string | null;
    catalogPublishedDirNames: ReadonlySet<string> | null;
    onPublishToCatalog: (dirName: string) => void;
}

export const PaletteForkFamily = memo(function PaletteForkFamily({
    rootKey,
    members,
    activePackageKey,
    setActivePackageKey,
    packagesPaletteEditMode,
    stagedRowsByPackageKey,
    removedKindIdsByPackageKey,
    forkManualPickByRoot,
    setForkManualPickByRoot,
    openWizardForPaletteSection,
    catalogMetadataLoaded,
    catalogPublishAllowed,
    publishingPackageKey,
    catalogPublishedDirNames,
    onPublishToCatalog,
}: PaletteForkFamilyProps) {
    const manualPick = forkManualPickByRoot[rootKey];
    const resolved = useMemo(
        () => resolveForkFamilySelectionKey(rootKey, members, activePackageKey ?? "", manualPick),
        [rootKey, members, activePackageKey, manualPick],
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

    const stagedInstalledRows = stagedRowsByPackageKey[selectedGroup.key] ?? [];
    const removedKindIds = removedKindIdsByPackageKey[selectedGroup.key] ?? [];
    const forkPublished =
        catalogPublishedDirNames != null && catalogPublishedDirNames.has(selectedGroup.key);

    const hasPendingEdits = stagedInstalledRows.length > 0 || removedKindIds.length > 0;
    const canOpenStagedFf = packagesPaletteEditMode && hasPendingEdits;
    const canOpenForkFf = packagesPaletteEditMode && !hasPendingEdits;
    const canOpenFactoryFf = canOpenStagedFf || canOpenForkFf;

    const onForkPickedFromPalette = useCallback(
        (next: string) => {
            setForkManualPickByRoot((prev) => ({ ...prev, [rootKey]: next }));
            setActivePackageKey(next);
            try {
                sessionStorage.setItem(FORK_SELECTION_SESSION_PREFIX + rootKey, next);
            } catch {
                /* noop */
            }
        },
        [rootKey, setActivePackageKey, setForkManualPickByRoot],
    );

    const forkPickerOptions = useMemo(
        () => members.map((m) => ({ key: m.key, label: m.name })),
        [members],
    );

    const familyTitle = useMemo(
        () => forkFamilyRootDisplayName(rootKey, members),
        [rootKey, members],
    );

    return (
        <div className={packageStyles.packageForkFamily}>
            <div className={packageStyles.packageForkFamilyToolbar}>
                <div className={packageStyles.packageForkFamilyToolbarText}>
                    <div className={packageStyles.packageForkFamilyTitleRow}>
                        <span
                            className={
                                canOpenFactoryFf
                                    ? `${packageStyles.packageForkFamilyTitle} ${packageStyles.packageForkFactoryTitleInteractive}`
                                    : packageStyles.packageForkFamilyTitle
                            }
                            role={canOpenFactoryFf ? "button" : undefined}
                            tabIndex={canOpenFactoryFf ? 0 : undefined}
                            title={
                                selectedGroup.label !== familyTitle
                                    ? `${familyTitle} — ${selectedGroup.label}`
                                    : canOpenStagedFf
                                      ? "Open Node Factory with staged edits"
                                      : canOpenForkFf
                                        ? "Fork this package in Node Factory"
                                        : familyTitle
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
                            {familyTitle}
                        </span>
                        {canOpenFactoryFf ? (
                            <button
                                type="button"
                                className={packageStyles.packageForkFamilyFactoryPen}
                                title={canOpenStagedFf ? "Open Node Factory with staged edits" : "Fork in Node Factory"}
                                aria-label={`Node Factory — ${familyTitle}`}
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
                                busy={publishingPackageKey === selectedGroup.key}
                                onPublish={onPublishToCatalog}
                            />
                        ) : null}
                    </div>
                    <span className={packageStyles.packageForkFamilySubtitle} title={rootKey}>
                        Family root {rootKey} · {members.length} forks
                    </span>
                </div>
                <span className={packageStyles.packageSummaryCount}>{members.length}</span>
            </div>
            <ForkFamilyPicker
                variant="dock"
                rootKey={rootKey}
                options={forkPickerOptions}
                value={resolved}
                onChange={onForkPickedFromPalette}
            />
            <InstalledPackageAccordion
                group={selectedGroup}
                summaryTitle={familyTitle}
                activePackageKey={activePackageKey}
                setActivePackageKey={setActivePackageKey}
                packagesPaletteEditMode={packagesPaletteEditMode}
                stagedInstalledRows={stagedInstalledRows}
                openWizardForPaletteSection={openWizardForPaletteSection}
                catalogMetadataLoaded={catalogMetadataLoaded}
                catalogPublishAllowed={catalogPublishAllowed}
                isCatalogPublished={forkPublished}
                publishingPackageKey={publishingPackageKey}
                onPublishToCatalog={onPublishToCatalog}
                showCatalogPublishInSummary={false}
            />
        </div>
    );
});

import React, { memo, useCallback, useMemo } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faPenToSquare } from "@fortawesome/free-solid-svg-icons";
import { useReactFlow } from "reactflow";
import type { PackageStagedRow } from "../../../../providers/PackagePaletteContext";
import { usePackagePalette } from "../../../../providers/PackagePaletteContext";
import { CatalogPublishPill } from "../../../packages/CatalogPublishPill";
import type { PackagePaletteGroup } from "./model";
import {
    canvasKindLabelForNodeId,
    normalizedStagedReplacementLabels,
    packageDescriptorsAfterPaletteEdits,
} from "./model";
import { PackageCanvasDropSlot, PackageKindRow, PackageStagedCanvasRow } from "./PackagePaletteRows";
import packageStyles from "./ToolsMenuPackagePalette.module.css";

export interface InstalledPackageAccordionProps {
    group: PackagePaletteGroup;
    activePackageKey: string | null;
    setActivePackageKey: (k: string | null) => void;
    packagesPaletteEditMode: boolean;
    stagedInstalledRows: readonly PackageStagedRow[];
    openWizardForPaletteSection: (sectionKey: string, opts: { group?: PackagePaletteGroup }) => void;
    catalogMetadataLoaded: boolean;
    catalogPublishAllowed: boolean;
    isCatalogPublished: boolean;
    publishingPackageKey: string | null;
    onPublishToCatalog: (dirName: string) => void;
    /** When false, omit the chip next to the summary title (e.g. fork toolbar already shows it). */
    showCatalogPublishInSummary?: boolean;
    /** Override `group.name` in the summary (e.g. fork families use the root package title). */
    summaryTitle?: string;
}

export const InstalledPackageAccordion = memo(function InstalledPackageAccordion({
    group,
    activePackageKey,
    setActivePackageKey,
    packagesPaletteEditMode,
    stagedInstalledRows,
    openWizardForPaletteSection,
    catalogMetadataLoaded,
    catalogPublishAllowed,
    isCatalogPublished,
    publishingPackageKey,
    onPublishToCatalog,
    showCatalogPublishInSummary = true,
    summaryTitle,
}: InstalledPackageAccordionProps) {
    const rowTitle = summaryTitle ?? group.name;
    const { getNodes } = useReactFlow();
    const { removedKindIdsByPackageKey } = usePackagePalette();
    const removedKindIds = removedKindIdsByPackageKey[group.key] ?? [];
    const labelForNodeId = useCallback(
        (nodeId: string) => canvasKindLabelForNodeId(nodeId, getNodes()),
        [getNodes],
    );
    const replacementLabels = useMemo(
        () => normalizedStagedReplacementLabels(stagedInstalledRows, labelForNodeId),
        [labelForNodeId, stagedInstalledRows],
    );
    const visibleDescriptors = useMemo(
        () =>
            packagesPaletteEditMode
                ? packageDescriptorsAfterPaletteEdits(group.descriptors, removedKindIds, replacementLabels)
                : group.descriptors,
        [group.descriptors, packagesPaletteEditMode, removedKindIds, replacementLabels],
    );
    const countBadge = packagesPaletteEditMode
        ? visibleDescriptors.length + stagedInstalledRows.length
        : group.descriptors.length;
    const hasPendingEdits = stagedInstalledRows.length > 0 || removedKindIds.length > 0;
    const canOpenStaged = packagesPaletteEditMode && hasPendingEdits;
    const canOpenFork = packagesPaletteEditMode && !hasPendingEdits;
    const canOpenFactory = canOpenStaged || canOpenFork;
    return (
        <details
            className={`${packageStyles.packageDetails} ${group.key === activePackageKey ? packageStyles.packageDetailsSelected : ""}`}
        >
            <summary className={packageStyles.packageSummary} onClick={() => setActivePackageKey(group.key)}>
                <div className={packageStyles.packageSummaryRow}>
                    <div className={packageStyles.packageSummaryTitleCluster}>
                        <span
                            className={packageStyles.packageSummaryTitle}
                            role={canOpenFactory ? "button" : undefined}
                            title={
                                group.label !== rowTitle
                                    ? `${rowTitle} — ${group.label}`
                                    : canOpenStaged
                                      ? "Open Node Factory with this package and staged edits"
                                      : canOpenFork
                                        ? "Fork this package in Node Factory (new install; source unchanged)"
                                        : rowTitle
                            }
                            // onClick={(e) => {
                            //     if (!canOpenFactory) return;
                            //     e.preventDefault();
                            //     e.stopPropagation();
                            //     setActivePackageKey(group.key);
                            //     openWizardForPaletteSection(group.key, { group });
                            // }}
                        >
                            {rowTitle}
                        </span>
                        {/* {canOpenFactory ? (
                            <button
                                type="button"
                                className={packageStyles.packageSummaryFactoryPen}
                                title={canOpenStaged ? "Open Node Factory with staged edits" : "Fork in Node Factory"}
                                aria-label={`Node Factory — ${group.name}`}
                                onClick={(e) => {
                                    e.preventDefault();
                                    e.stopPropagation();
                                    setActivePackageKey(group.key);
                                    openWizardForPaletteSection(group.key, { group });
                                }}
                            >
                                <FontAwesomeIcon icon={faPenToSquare} />
                            </button>
                        ) : null} */}
                        {catalogMetadataLoaded && showCatalogPublishInSummary ? (
                            <CatalogPublishPill
                                variant="dock"
                                dirName={group.key}
                                published={isCatalogPublished}
                                allowPublish={catalogPublishAllowed}
                                busy={publishingPackageKey === group.key}
                                onPublish={onPublishToCatalog}
                            />
                        ) : null}
                    </div>
                    <span className={packageStyles.packageSummaryCount}>{countBadge}</span>
                </div>
            </summary>
            <div className={`${packageStyles.packageKindGrid}${packagesPaletteEditMode ? ` ${packageStyles.packageKindGridEdit}` : ""}`}>
                {visibleDescriptors.map((desc) => (
                    <PackageKindRow
                        key={desc.id}
                        desc={desc}
                        packageSectionKey={group.key}
                        packagesPaletteEditMode={packagesPaletteEditMode}
                        tooltipPlacement="right"
                    />
                ))}
                {packagesPaletteEditMode
                    ? stagedInstalledRows.map((row) => (
                          <PackageStagedCanvasRow
                              key={row.rowId}
                              packageSectionKey={group.key}
                              rowId={row.rowId}
                              canvasNodeId={row.canvasNodeId}
                          />
                      ))
                    : null}
                {packagesPaletteEditMode ? <PackageCanvasDropSlot packageSectionKey={group.key} /> : null}
            </div>
        </details>
    );
});

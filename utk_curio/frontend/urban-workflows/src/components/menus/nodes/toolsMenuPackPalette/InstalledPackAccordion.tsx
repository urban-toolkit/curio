import React, { memo, useCallback, useMemo } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faPenToSquare } from "@fortawesome/free-solid-svg-icons";
import { useReactFlow } from "reactflow";
import type { PackStagedRow } from "../../../../providers/PackPaletteContext";
import { usePackPalette } from "../../../../providers/PackPaletteContext";
import { CatalogPublishPill } from "../../../packs/CatalogPublishPill";
import type { PackPaletteGroup } from "./model";
import {
    canvasKindLabelForNodeId,
    normalizedStagedReplacementLabels,
    packDescriptorsAfterPaletteEdits,
} from "./model";
import { PackCanvasDropSlot, PackKindRow, PackStagedCanvasRow } from "./PackPaletteRows";
import packStyles from "./ToolsMenuPackPalette.module.css";

export interface InstalledPackAccordionProps {
    group: PackPaletteGroup;
    activePackKey: string | null;
    setActivePackKey: (k: string | null) => void;
    packsPaletteEditMode: boolean;
    stagedInstalledRows: readonly PackStagedRow[];
    openWizardForPaletteSection: (sectionKey: string, opts: { group?: PackPaletteGroup }) => void;
    catalogMetadataLoaded: boolean;
    catalogPublishAllowed: boolean;
    isCatalogPublished: boolean;
    publishingPackKey: string | null;
    onPublishToCatalog: (dirName: string) => void;
    /** When false, omit the chip next to the summary title (e.g. fork toolbar already shows it). */
    showCatalogPublishInSummary?: boolean;
}

export const InstalledPackAccordion = memo(function InstalledPackAccordion({
    group,
    activePackKey,
    setActivePackKey,
    packsPaletteEditMode,
    stagedInstalledRows,
    openWizardForPaletteSection,
    catalogMetadataLoaded,
    catalogPublishAllowed,
    isCatalogPublished,
    publishingPackKey,
    onPublishToCatalog,
    showCatalogPublishInSummary = true,
}: InstalledPackAccordionProps) {
    const { getNodes } = useReactFlow();
    const { removedKindIdsByPackKey } = usePackPalette();
    const removedKindIds = removedKindIdsByPackKey[group.key] ?? [];
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
            packsPaletteEditMode
                ? packDescriptorsAfterPaletteEdits(group.descriptors, removedKindIds, replacementLabels)
                : group.descriptors,
        [group.descriptors, packsPaletteEditMode, removedKindIds, replacementLabels],
    );
    const countBadge = packsPaletteEditMode
        ? visibleDescriptors.length + stagedInstalledRows.length
        : group.descriptors.length;
    const hasPendingEdits = stagedInstalledRows.length > 0 || removedKindIds.length > 0;
    const canOpenStaged = packsPaletteEditMode && hasPendingEdits;
    const canOpenFork = packsPaletteEditMode && !hasPendingEdits;
    const canOpenFactory = canOpenStaged || canOpenFork;
    return (
        <details
            className={`${packStyles.packDetails} ${group.key === activePackKey ? packStyles.packDetailsSelected : ""}`}
        >
            <summary className={packStyles.packSummary} onClick={() => setActivePackKey(group.key)}>
                <div className={packStyles.packSummaryRow}>
                    <div className={packStyles.packSummaryTitleCluster}>
                        <span
                            className={packStyles.packSummaryTitle}
                            role={canOpenFactory ? "button" : undefined}
                            title={
                                group.label !== group.name
                                    ? group.label
                                    : canOpenStaged
                                      ? "Open Node Factory with this pack and staged edits"
                                      : canOpenFork
                                        ? "Fork this pack in Node Factory (new install; source unchanged)"
                                        : undefined
                            }
                            onClick={(e) => {
                                if (!canOpenFactory) return;
                                e.preventDefault();
                                e.stopPropagation();
                                setActivePackKey(group.key);
                                openWizardForPaletteSection(group.key, { group });
                            }}
                        >
                            {group.name}
                        </span>
                        {canOpenFactory ? (
                            <button
                                type="button"
                                className={packStyles.packSummaryFactoryPen}
                                title={canOpenStaged ? "Open Node Factory with staged edits" : "Fork in Node Factory"}
                                aria-label={`Node Factory — ${group.name}`}
                                onClick={(e) => {
                                    e.preventDefault();
                                    e.stopPropagation();
                                    setActivePackKey(group.key);
                                    openWizardForPaletteSection(group.key, { group });
                                }}
                            >
                                <FontAwesomeIcon icon={faPenToSquare} />
                            </button>
                        ) : null}
                        {catalogMetadataLoaded && showCatalogPublishInSummary ? (
                            <CatalogPublishPill
                                variant="dock"
                                dirName={group.key}
                                published={isCatalogPublished}
                                allowPublish={catalogPublishAllowed}
                                busy={publishingPackKey === group.key}
                                onPublish={onPublishToCatalog}
                            />
                        ) : null}
                    </div>
                    <span className={packStyles.packSummaryCount}>{countBadge}</span>
                </div>
            </summary>
            <div className={`${packStyles.packKindGrid}${packsPaletteEditMode ? ` ${packStyles.packKindGridEdit}` : ""}`}>
                {visibleDescriptors.map((desc) => (
                    <PackKindRow
                        key={desc.id}
                        desc={desc}
                        packSectionKey={group.key}
                        packsPaletteEditMode={packsPaletteEditMode}
                        tooltipPlacement="right"
                    />
                ))}
                {packsPaletteEditMode
                    ? stagedInstalledRows.map((row) => (
                          <PackStagedCanvasRow
                              key={row.rowId}
                              packSectionKey={group.key}
                              rowId={row.rowId}
                              canvasNodeId={row.canvasNodeId}
                          />
                      ))
                    : null}
                {packsPaletteEditMode ? <PackCanvasDropSlot packSectionKey={group.key} /> : null}
            </div>
        </details>
    );
});

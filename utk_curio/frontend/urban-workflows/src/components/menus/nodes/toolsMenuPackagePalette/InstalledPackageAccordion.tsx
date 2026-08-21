import React, { memo, useCallback, useState } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faDownload, faPenToSquare } from "@fortawesome/free-solid-svg-icons";
import { packagesApi } from "../../../../api/packagesApi";
import { useToastContext } from "../../../../providers/ToastProvider";
import { CatalogPublishPill } from "../../../packages/CatalogPublishPill";
import { PackageMetadataModal } from "../../../packages/editing";
import { PaletteAccordion } from "../paletteAccordion";
import type { PackagePaletteGroup } from "./model";
import { PackageTemplateRow } from "./PackagePaletteRows";
import packageStyles from "./ToolsMenuPackagePalette.module.css";

export interface InstalledPackageAccordionProps {
    group: PackagePaletteGroup;
    activePackageKey: string | null;
    setActivePackageKey: (k: string | null) => void;
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
    catalogMetadataLoaded,
    catalogPublishAllowed,
    isCatalogPublished,
    publishingPackageKey,
    onPublishToCatalog,
    showCatalogPublishInSummary = true,
    summaryTitle,
}: InstalledPackageAccordionProps) {
    const rowTitle = summaryTitle ?? group.name;
    const { showToast } = useToastContext();
    const [metadataOpen, setMetadataOpen] = useState(false);
    const isReadOnly = !!group.descriptors[0]?.package?.readOnly;

    const onExportClick = useCallback(
        async (e: React.MouseEvent<HTMLButtonElement>) => {
            e.preventDefault();
            e.stopPropagation();
            try {
                await packagesApi.download(group.key);
            } catch (err) {
                showToast(
                    `Couldn't export ${group.key}: ${(err as Error)?.message ?? "unknown error"}`,
                    "error",
                );
            }
        },
        [group.key, showToast],
    );
    const actions = (
        <>
            <button
                type="button"
                className={packageStyles.packageSummaryExportBtn}
                title="Export package"
                aria-label={`Export ${group.name} as a .curio.zip archive`}
                data-curio-package-palette-node-action="true"
                onMouseDown={(e) => {
                    e.stopPropagation();
                    e.preventDefault();
                }}
                onClick={(e) => void onExportClick(e)}
            >
                <FontAwesomeIcon icon={faDownload} aria-hidden />
            </button>
            {!isReadOnly ? (
                <button
                    type="button"
                    className={packageStyles.packageSummaryExportBtn}
                    title="Edit package metadata"
                    aria-label={`Edit metadata for ${group.name}`}
                    data-curio-package-palette-node-action="true"
                    onMouseDown={(e) => {
                        e.stopPropagation();
                        e.preventDefault();
                    }}
                    onClick={(e) => {
                        e.stopPropagation();
                        e.preventDefault();
                        setMetadataOpen(true);
                    }}
                >
                    <FontAwesomeIcon icon={faPenToSquare} aria-hidden />
                </button>
            ) : null}
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
        </>
    );

    return (
        <PaletteAccordion
            title={rowTitle}
            titleTooltip={group.label !== rowTitle ? `${rowTitle} — ${group.label}` : rowTitle}
            count={group.descriptors.length}
            actions={actions}
            selected={group.key === activePackageKey}
            onSummaryClick={() => setActivePackageKey(group.key)}
        >
            {group.descriptors.map((desc) => (
                <PackageTemplateRow
                    key={desc.id}
                    desc={desc}
                    tooltipPlacement="right"
                />
            ))}
            {metadataOpen ? (
                <PackageMetadataModal
                    dirName={group.key}
                    onClose={() => setMetadataOpen(false)}
                />
            ) : null}
        </PaletteAccordion>
    );
});

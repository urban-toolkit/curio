import React, { memo, useCallback, useState } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faCircleInfo, faDownload, faPenToSquare } from "@fortawesome/free-solid-svg-icons";
import { packagesApi, type PackagePayload } from "../../../../api/packagesApi";
import { PackageDetailModal } from "../../../packages/publishing/PackageDetailModal";
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
    const [detailPkg, setDetailPkg] = useState<PackagePayload | null>(null);
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
    // The palette holds only a package's summary, so its details are read on
    // demand: the account's copy first, then the shared catalog's.
    const onDetailsClick = useCallback(
        async (e: React.MouseEvent<HTMLButtonElement>) => {
            e.preventDefault();
            e.stopPropagation();
            try {
                const mine = await packagesApi.listInstalled();
                let pkg = mine.packages.find((p) => p.dirName === group.key) ?? null;
                if (!pkg) {
                    const shared = await packagesApi.catalog();
                    pkg = shared.packages.find((p) => p.dirName === group.key) ?? null;
                }
                if (pkg) setDetailPkg(pkg);
                else showToast(`Couldn't find the details of ${group.name}.`, "error");
            } catch (err) {
                showToast(
                    `Couldn't load the details of ${group.name}: ${(err as Error)?.message ?? "unknown error"}`,
                    "error",
                );
            }
        },
        [group.key, group.name, showToast],
    );
    const actions = (
        <>
            {/* The way into the package's details, as every catalog card offers. */}
            <button
                type="button"
                className={packageStyles.packageSummaryExportBtn}
                title="View details"
                aria-label={`View ${group.name} details`}
                data-curio-package-palette-node-action="true"
                onMouseDown={(e) => {
                    e.stopPropagation();
                    e.preventDefault();
                }}
                onClick={(e) => void onDetailsClick(e)}
            >
                <FontAwesomeIcon icon={faCircleInfo} aria-hidden />
            </button>
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
            {detailPkg ? (
                <PackageDetailModal
                    pkg={detailPkg}
                    isPublished={catalogMetadataLoaded ? isCatalogPublished : undefined}
                    onClose={() => setDetailPkg(null)}
                />
            ) : null}
        </PaletteAccordion>
    );
});

import React, { memo, useCallback, useEffect, useMemo } from "react";
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
    forkManualPickByRoot: Record<string, string>;
    setForkManualPickByRoot: React.Dispatch<React.SetStateAction<Record<string, string>>>;
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
    forkManualPickByRoot,
    setForkManualPickByRoot,
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

    const forkPublished =
        catalogPublishedDirNames != null && catalogPublishedDirNames.has(selectedGroup.key);

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
                            className={packageStyles.packageForkFamilyTitle}
                            title={
                                selectedGroup.label !== familyTitle
                                    ? `${familyTitle} — ${selectedGroup.label}`
                                    : familyTitle
                            }
                        >
                            {familyTitle}
                        </span>
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

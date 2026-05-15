import React, { memo, Fragment, useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faCirclePlus, faCube, faChevronDown, faChevronUp, faForwardStep, faPenToSquare, faXmark } from "@fortawesome/free-solid-svg-icons";
import { Tooltip, OverlayTrigger } from "react-bootstrap";
import { useReactFlow, useStore } from "reactflow";
import { packsApi, refreshPackRegistry } from "../../../api/packsApi";
import { PACK_STAGING_MIME } from "../../../constants/packPaletteStaging";
import { getPaletteNodeTypes, subscribeToRegistry, tryGetNodeDescriptor } from "../../../registry";
import { NodeCategory, NodeDescriptor, NodeKindId, NodePackMeta } from "../../../registry/types";
import { useFlowContext } from "../../../providers/FlowProvider";
import { useToastContext } from "../../../providers/ToastProvider";
import { useTemplateContext } from "../../../providers/TemplateProvider";
import { useUserContext } from "../../../providers/UserProvider";
import { draftPackSectionKey, usePackPalette, type PackStagedRow } from "../../../providers/PackPaletteContext";
import { useNodeFactoryModal } from "../../../providers/NodeFactoryModalProvider";
import {
    buildDraftForPaletteSection,
    buildFactoryInstallEnvelope,
    draftForkFromInstalledPackPayload,
    draftFromInstalledPackPayload,
} from "../../../utils/palettePackFactoryDraft";
import { toApiPayload } from "../../../pages/nodes/factoryDraftModel";
import type { PackPayload } from "../../../api/packsApi";
import {
    FORK_SELECTION_SESSION_PREFIX,
    filterForkParentHiddenPalettePackGroups,
    partitionPalettePackGroups,
    resolveForkFamilySelectionKey,
    type PalettePackRow,
} from "../../../utils/forkPackLineage";
import { getFlowNodeCanonicalType } from "../../../utils/flowNodeCanonicalType";
import { CatalogPublishPill } from "../../packs/CatalogPublishPill";
import styles from "./ToolsMenu.module.css";

/** Changes whenever pack descriptors are registered — same signal as the outer palette rerender. */
function paletteDescriptorBootstrapKey(): string {
    const types = getPaletteNodeTypes();
    return `${types.length}|${types.map((d) => d.id).join(",")}`;
}

const CATEGORY_SHORT: Record<NodeCategory, string> = {
    data: "Data",
    computation: "Compute",
    vis_grammar: "Viz",
    vis_simple: "Chart",
    flow: "Flow",
};

type TooltipSide = "left" | "right";

const DraggableTool = memo(function DraggableTool({
    nodeType,
    icon,
    tooltip,
    tutorialID,
    badge,
    tooltipPlacement = "right",
}: {
    nodeType: NodeKindId;
    icon: any;
    tooltip: string;
    tutorialID?: string;
    badge?: string;
    tooltipPlacement?: TooltipSide;
}) {
    return (
        <OverlayTrigger
            placement={tooltipPlacement}
            delay={overlayTriggerProps}
            overlay={<Tooltip>{tooltip}</Tooltip>}
        >
            <div
                id={tutorialID}
                className={styles.optionStyle}
                draggable
                onDragStart={(event) => {
                    event.dataTransfer.setData("application/reactflow", nodeType);
                    event.dataTransfer.effectAllowed = "move";
                }}
            >
                <FontAwesomeIcon icon={icon} className={styles.iconStyle} />
                {badge && <span className={styles.iconBadge}>{badge}</span>}
            </div>
        </OverlayTrigger>
    );
});

const PackKindRow = memo(function PackKindRow({
    desc,
    tooltipPlacement = "right",
}: {
    desc: NodeDescriptor;
    tooltipPlacement?: TooltipSide;
}) {
    const { setNodes } = useReactFlow();

    const selectOnCanvas = useCallback(
        (e: React.MouseEvent) => {
            e.stopPropagation();
            e.preventDefault();
            setNodes((nds) =>
                nds.map((n) => ({
                    ...n,
                    selected: getFlowNodeCanonicalType(n) === desc.id,
                })),
            );
        },
        [desc.id, setNodes],
    );

    return (
        <OverlayTrigger
            placement={tooltipPlacement}
            delay={overlayTriggerProps}
            overlay={
                <Tooltip>
                    {desc.label}
                    {desc.description ? ` — ${desc.description}` : ""}
                </Tooltip>
            }
        >
            <div className={styles.packKindRow}>
                <div
                    className={styles.packKindRowDrag}
                    draggable
                    onDragStart={(event) => {
                        event.dataTransfer.setData("application/reactflow", String(desc.id));
                        event.dataTransfer.effectAllowed = "move";
                    }}
                >
                    <FontAwesomeIcon icon={desc.icon} className={styles.iconStyle} />
                    {desc.badge ? <span className={styles.iconBadge}>{desc.badge}</span> : null}
                </div>
                <button
                    type="button"
                    className={styles.packKindRowMeta}
                    onClick={selectOnCanvas}
                    title="Select nodes of this kind on the canvas"
                >
                    <span className={styles.packKindRowLabel}>{desc.label}</span>
                    <span className={styles.packKindCategoryChip}>{CATEGORY_SHORT[desc.category]}</span>
                </button>
            </div>
        </OverlayTrigger>
    );
});

function parseStagingPayload(dataTransfer: DataTransfer): string | null {
    const raw = dataTransfer.getData(PACK_STAGING_MIME).trim();
    if (!raw) return null;
    try {
        const parsed = JSON.parse(raw) as { nodeId?: string };
        return typeof parsed.nodeId === "string" ? parsed.nodeId : null;
    } catch {
        return null;
    }
}

/** Trailing dashed drop target; each successful drop appends a staged row and this slot stays last. */
const PackCanvasDropSlot = memo(function PackCanvasDropSlot({
    packSectionKey,
}: {
    packSectionKey: string;
}) {
    const [hover, setHover] = useState(false);
    const { stageCanvasNodeOnPackSection } = usePackPalette();

    const allowsMime = useCallback((dt: DataTransfer) => {
        return Array.from(dt.types).includes(PACK_STAGING_MIME);
    }, []);

    const onDragOver = useCallback(
        (event: React.DragEvent) => {
            if (!allowsMime(event.dataTransfer)) return;
            event.preventDefault();
            event.stopPropagation();
            event.dataTransfer.dropEffect = "copy";
        },
        [allowsMime],
    );

    const onDrop = useCallback(
        (event: React.DragEvent) => {
            event.preventDefault();
            event.stopPropagation();
            setHover(false);
            
            const canvasNodeId = parseStagingPayload(event.dataTransfer);
            if (!canvasNodeId) return;
            stageCanvasNodeOnPackSection(packSectionKey, canvasNodeId);
        },
        [packSectionKey, stageCanvasNodeOnPackSection],
    );

    const onDragEnter = useCallback(
        (event: React.DragEvent) => {
            if (allowsMime(event.dataTransfer)) setHover(true);
        },
        [allowsMime],
    );

    const onDragLeave = useCallback((event: React.DragEvent) => {
        if (event.currentTarget === event.target) setHover(false);
    }, []);

    return (
        <div
            className={`${styles.packCanvasDropSlot} ${hover ? styles.packCanvasDropSlotActive : ""}`}
            onDragOver={onDragOver}
            onDrop={onDrop}
            onDragEnter={onDragEnter}
            onDragLeave={onDragLeave}
            role="region"
            aria-label="Drop a canvas node here to attach it to this pack while editing."
        >
            <span className={styles.packCanvasDropSlotInner}>Drop canvas node</span>
        </div>
    );
});

const PackStagedCanvasRow = memo(function PackStagedCanvasRow({
    packSectionKey,
    rowId,
    canvasNodeId,
}: {
    packSectionKey: string;
    rowId: string;
    canvasNodeId: string;
}) {
    const { removeStagedRowFromSection } = usePackPalette();
    const { setNodes } = useReactFlow();

    const label = useStore(
        useCallback((s: any) => {
            const n = s.nodeInternals?.get(canvasNodeId);
            if (!n?.data) return "Node";
            const d = n.data as { templateName?: string; nodeType?: string };
            const tmpl = typeof d.templateName === "string" ? d.templateName.trim() : "";
            if (tmpl) return tmpl;
            const t = String(d.nodeType ?? n.type ?? "");
            return tryGetNodeDescriptor(t as NodeKindId)?.label ?? t ?? canvasNodeId;
        }, [canvasNodeId]),
    );

    const selectOnCanvas = useCallback(
        (e: React.MouseEvent) => {
            e.stopPropagation();
            setNodes((nds) => nds.map((n) => ({ ...n, selected: n.id === canvasNodeId })));
        },
        [canvasNodeId, setNodes],
    );

    return (
        <div className={styles.packStagedRow}>
            <span className={styles.packStagedRowGlyph} aria-hidden />
            <button type="button" className={styles.packStagedRowMeta} onClick={selectOnCanvas} title="Select this node on the canvas">
                <span className={styles.packStagedRowLabel}>{label}</span>
                <span className={styles.packStagedRowHint}>Canvas instance</span>
            </button>
            <button
                type="button"
                className={styles.packStagedRowRemove}
                title="Remove from pack staging list"
                aria-label="Remove from pack staging list"
                onClick={(e) => {
                    e.stopPropagation();
                    removeStagedRowFromSection(packSectionKey, rowId);
                }}
            >
                <FontAwesomeIcon icon={faXmark} />
            </button>
        </div>
    );
});

// Groups (top → bottom) for the BUILT-IN section. vis_grammar and vis_simple
// share one block; flow nodes (e.g. Merge Flow) live in the top data block.
const PALETTE_GROUPS: NodeCategory[][] = [
    ['data', 'flow'],
    ['computation'],
    ['vis_grammar', 'vis_simple'],
];

function groupPaletteTypes(descriptors: NodeDescriptor[]): NodeDescriptor[][] {
    return PALETTE_GROUPS
        .map(categories => descriptors.filter(d => categories.includes(d.category)))
        .filter(group => group.length > 0);
}

function renderGroup(group: NodeDescriptor[], key: string, tooltipPlacement: TooltipSide = "right") {
    return (
        <div key={key} className={styles.containerStyle}>
            {group.map(desc => (
                <DraggableTool
                    key={desc.id}
                    nodeType={desc.id}
                    icon={desc.icon}
                    tooltip={desc.label}
                    tutorialID={desc.tutorialId}
                    badge={desc.badge}
                    tooltipPlacement={tooltipPlacement}
                />
            ))}
        </div>
    );
}

interface PackPaletteGroup {
    key: string;
    label: string;
    descriptors: NodeDescriptor[];
}

function formatPackSectionLabel(meta: NodePackMeta): string {
    const coord = `${meta.packId}@${meta.major}`;
    if (meta.publisher?.trim()) {
        return `${meta.publisher} · ${coord}`;
    }
    return coord;
}

/** One group per installed pack coordinate (`packId@major`). */
function groupPalettePacks(packTypes: NodeDescriptor[]): PackPaletteGroup[] {
    const byKey = new Map<string, NodeDescriptor[]>();
    for (const d of packTypes) {
        if (d.source !== "pack" || !d.pack) continue;
        const key = `${d.pack.packId}@${d.pack.major}`;
        if (!byKey.has(key)) byKey.set(key, []);
        byKey.get(key)!.push(d);
    }
    return Array.from(byKey.entries())
        .map(([key, descriptors]) => {
            const sorted = [...descriptors].sort(
                (a, b) => (a.paletteOrder ?? 999) - (b.paletteOrder ?? 999),
            );
            const label = formatPackSectionLabel(sorted[0].pack!);
            return { key, label, descriptors: sorted };
        })
        .sort((a, b) => a.label.localeCompare(b.label, undefined, { sensitivity: "base" }));
}

/**
 * Mirrors what the PACKS dropdown lists: filtered groups only; fork-family rows count the
 * **selected** fork's kinds (+ staged canvas rows when edit mode is on).
 */
function visiblePaletteTriggerKindsCount(opts: {
    paletteRows: PalettePackRow<PackPaletteGroup>[];
    packsPaletteEditMode: boolean;
    stagedRowsByPackKey: Readonly<Record<string, readonly PackStagedRow[]>>;
    draftPackSectionIds: readonly string[];
    activePackKey: string | null;
    forkManualPickByRoot: Record<string, string>;
}): number {
    const {
        paletteRows,
        packsPaletteEditMode,
        stagedRowsByPackKey,
        draftPackSectionIds,
        activePackKey,
        forkManualPickByRoot,
    } = opts;

    let n = 0;
    if (packsPaletteEditMode) {
        for (const draftId of draftPackSectionIds) {
            const sectionKey = draftPackSectionKey(draftId);
            n += (stagedRowsByPackKey[sectionKey] ?? []).length;
        }
    }
    const activeKey = activePackKey ?? "";
    for (const row of paletteRows) {
        if (row.kind === "singleton") {
            const staged = stagedRowsByPackKey[row.group.key] ?? [];
            n += row.group.descriptors.length + (packsPaletteEditMode ? staged.length : 0);
            continue;
        }
        const resolverMembers = row.members.map((m) => ({ key: m.key }));
        const resolvedDir = resolveForkFamilySelectionKey(
            row.rootKey,
            resolverMembers,
            activeKey,
            forkManualPickByRoot[row.rootKey],
        );
        const g = row.members.find((m) => m.key === resolvedDir) ?? row.members[0]!;
        const staged = stagedRowsByPackKey[g.key] ?? [];
        n += g.descriptors.length + (packsPaletteEditMode ? staged.length : 0);
    }
    return n;
}

interface InstalledPackAccordionProps {
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

const InstalledPackAccordion = memo(function InstalledPackAccordion({
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
    const countBadge = packsPaletteEditMode ? group.descriptors.length + stagedInstalledRows.length : group.descriptors.length;
    const canOpenStaged = packsPaletteEditMode && stagedInstalledRows.length > 0;
    const canOpenFork = packsPaletteEditMode && stagedInstalledRows.length === 0;
    const canOpenFactory = canOpenStaged || canOpenFork;
    return (
        <details className={`${styles.packDetails} ${group.key === activePackKey ? styles.packDetailsSelected : ""}`}>
            <summary
                className={styles.packSummary}
                onClick={() => setActivePackKey(group.key)}
            >
                <div className={styles.packSummaryRow}>
                    <div className={styles.packSummaryTitleCluster}>
                        <span
                            className={styles.packSummaryTitle}
                            role={canOpenFactory ? "button" : undefined}
                            title={
                                canOpenStaged
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
                            {group.label}
                        </span>
                        {canOpenFactory ? (
                            <button
                                type="button"
                                className={styles.packSummaryFactoryPen}
                                title={canOpenStaged ? "Open Node Factory with staged edits" : "Fork in Node Factory"}
                                aria-label={`Node Factory — ${group.label}`}
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
                    <span className={styles.packSummaryCount}>{countBadge}</span>
                </div>
            </summary>
            <div className={styles.packKindGrid}>
                {group.descriptors.map((desc) => (
                    <PackKindRow key={desc.id} desc={desc} tooltipPlacement="right" />
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

interface PaletteForkFamilyProps {
    rootKey: string;
    members: PackPaletteGroup[];
    activePackKey: string | null;
    setActivePackKey: (k: string | null) => void;
    packsPaletteEditMode: boolean;
    stagedRowsByPackKey: Readonly<Record<string, readonly PackStagedRow[]>>;
    forkManualPickByRoot: Record<string, string>;
    setForkManualPickByRoot: React.Dispatch<React.SetStateAction<Record<string, string>>>;
    openWizardForPaletteSection: (sectionKey: string, opts: { group?: PackPaletteGroup }) => void;
    catalogMetadataLoaded: boolean;
    catalogPublishAllowed: boolean;
    publishingPackKey: string | null;
    catalogPublishedDirNames: ReadonlySet<string> | null;
    onPublishToCatalog: (dirName: string) => void;
}

const PaletteForkFamily = memo(function PaletteForkFamily({
    rootKey,
    members,
    activePackKey,
    setActivePackKey,
    packsPaletteEditMode,
    stagedRowsByPackKey,
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
    const forkPublished =
        catalogPublishedDirNames != null && catalogPublishedDirNames.has(selectedGroup.key);

    const canOpenStagedFf = packsPaletteEditMode && stagedInstalledRows.length > 0;
    const canOpenForkFf = packsPaletteEditMode && stagedInstalledRows.length === 0;
    const canOpenFactoryFf = canOpenStagedFf || canOpenForkFf;

    const onForkSelectChange = useCallback(
        (e: React.ChangeEvent<HTMLSelectElement>) => {
            const next = e.target.value;
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

    return (
        <div className={styles.packForkFamily}>
            <div className={styles.packForkFamilyToolbar}>
                <div className={styles.packForkFamilyToolbarText}>
                    <div className={styles.packForkFamilyTitleRow}>
                        <span
                            className={
                                canOpenFactoryFf
                                    ? `${styles.packForkFamilyTitle} ${styles.packForkFactoryTitleInteractive}`
                                    : styles.packForkFamilyTitle
                            }
                            role={canOpenFactoryFf ? "button" : undefined}
                            tabIndex={canOpenFactoryFf ? 0 : undefined}
                            title={
                                canOpenStagedFf
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
                            {formatPackSectionLabel(selectedGroup.descriptors[0].pack!)}
                        </span>
                        {canOpenFactoryFf ? (
                            <button
                                type="button"
                                className={styles.packForkFamilyFactoryPen}
                                title={canOpenStagedFf ? "Open Node Factory with staged edits" : "Fork in Node Factory"}
                                aria-label={`Node Factory — ${selectedGroup.label}`}
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
                    <span className={styles.packForkFamilySubtitle} title={rootKey}>
                        Family root {rootKey} · {members.length} forks
                    </span>
                </div>
                <span className={styles.packSummaryCount}>{members.length}</span>
            </div>
            <select
                className={styles.packForkFamilySelect}
                value={resolved}
                aria-label={`Select installed fork (${rootKey})`}
                onChange={onForkSelectChange}
            >
                {members.map((m) => (
                    <option key={m.key} value={m.key}>
                        {m.label}
                    </option>
                ))}
            </select>
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

const PacksPaletteDropdown = memo(function PacksPaletteDropdown({ groups }: { groups: PackPaletteGroup[] }) {
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
                // Refresh the installed pack on disk when this coord already exists so the Packs menu
                // shows merged kinds. Canvas workflow nodes keep their IDs and are untouched here.
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
        <div id="packs-palette" className={styles.packPaletteRoot} ref={rootRef}>
            <button
                type="button"
                className={`${styles.packPaletteTrigger} ${open ? styles.packPaletteTriggerOpen : ""}`}
                onClick={toggle}
                aria-expanded={open}
                aria-haspopup="true"
                title={open ? "Close pack nodes" : "Open pack nodes"}
            >
                <FontAwesomeIcon icon={faCube} className={styles.packPaletteTriggerIcon} />
                <span className={styles.packPaletteTriggerLabel}>Packs</span>
                <span className={styles.packPaletteTriggerCount}>{totalKindsDisplayed}</span>
                <FontAwesomeIcon icon={open ? faChevronUp : faChevronDown} className={styles.packPaletteTriggerChevron} />
            </button>
            {open && (
                <div className={styles.packPalettePanel} role="region" aria-label="Pack node kinds">
                    <div className={styles.packPaletteToolbar}>
                        {!packsPaletteEditMode ? (
                            <button
                                type="button"
                                className={styles.packEditToggle}
                                onClick={() => setPacksPaletteEditMode(true)}
                            >
                                Edit
                            </button>
                        ) : (
                            <>
                                <button
                                    type="button"
                                    className={styles.packToolbarBtnPrimary}
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
                                <button type="button" className={styles.packToolbarBtn} onClick={onCancelEdit}>
                                    Cancel
                                </button>
                            </>
                        )}
                    </div>
                    <div className={styles.packPalettePanelTitle}>Nodes by pack</div>
                    <div className={styles.packPaletteScroll}>
                        {packsPaletteEditMode ? (
                            <button
                                type="button"
                                className={styles.packAddSectionRow}
                                onClick={() => registerDraftPackSection()}
                            >
                                <FontAwesomeIcon icon={faCirclePlus} className={styles.packAddSectionIcon} aria-hidden />
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
                                          className={`${styles.packDetails} ${sectionKey === activePackKey ? styles.packDetailsSelected : ""}`}
                                      >
                                          <summary
                                              className={styles.packSummary}
                                              onClick={() => setActivePackKey(sectionKey)}
                                          >
                                              <div className={styles.packSummaryRow}>
                                                  <span
                                                      className={styles.packSummaryTitle}
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
                                                  <span className={styles.packSummaryCount}>{stagedRows.length}</span>
                                              </div>
                                          </summary>
                                          <div className={styles.packKindGrid}>
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

const NOOP = () => () => {};

const ToolsMenu = memo(function ToolsMenu() {
    // Re-render whenever the registry mutates (e.g. when pack descriptors
    // land asynchronously via packsClient.ts).
    const paletteVersion = useSyncExternalStore(
        typeof window !== "undefined" ? subscribeToRegistry : NOOP,
        paletteDescriptorBootstrapKey,
        () => "ssr",
    );
    void paletteVersion;

    const { user } = useUserContext();
    // Boot-time refresh can run before auth finishes (401 → empty palette). Re-sync whenever
    // the workflow canvas mounts for a signed-in user so Packs matches Nodes hub listing.
    useEffect(() => {
        const uid = user?.id;
        if (uid == null) return;
        void refreshPackRegistry();
    }, [user?.id]);

    const paletteTypes = getPaletteNodeTypes();
    const coreTypes = paletteTypes.filter(d => d.source !== 'pack');
    const packTypes = paletteTypes.filter(d => d.source === 'pack');
    const coreGroups = groupPaletteTypes(coreTypes);
    const packGroups = groupPalettePacks(packTypes);
    const { playAllNodes } = useFlowContext();
    return (
        <div id="tools-palette-dock" className={styles.paletteDock}>
            <div id="tools-menu" className={styles.builtinStack}>
                <div className={styles.menuStyle}>
                    <div className={styles.sectionHeader}>Built-in</div>
                    {coreGroups.map((group, i) => (
                        <Fragment key={`core-${i}`}>
                            {i > 0 && <div className={styles.divider} />}
                            {renderGroup(group, `core-group-${i}`)}
                        </Fragment>
                    ))}
                </div>
                <button
                    className={styles.playAllButton}
                    onClick={playAllNodes}
                    title="Run all nodes"
                >
                    <FontAwesomeIcon icon={faForwardStep} />
                </button>
            </div>
            <PacksPaletteDropdown groups={packGroups} />
        </div>
    );
});

export default ToolsMenu;

const overlayTriggerProps = {
    show: 120,
    hide: 10,
};

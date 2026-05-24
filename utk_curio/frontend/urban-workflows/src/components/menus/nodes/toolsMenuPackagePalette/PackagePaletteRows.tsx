import React, { memo, useCallback, useState } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faCircleMinus, faXmark } from "@fortawesome/free-solid-svg-icons";
import { Tooltip, OverlayTrigger } from "react-bootstrap";
import { useReactFlow, useStore } from "reactflow";
import { NODE_CATEGORY_SHORT_LABEL } from "../../../../constants/nodeCategoryShortLabels";
import { PACKAGE_STAGING_MIME } from "../../../../constants/packagePaletteStaging";
import { tryGetNodeDescriptor } from "../../../../registry";
import { NodeDescriptor, NodeKindId } from "../../../../registry/types";
import { usePackagePalette } from "../../../../providers/PackagePaletteContext";
import { getFlowNodeCanonicalType } from "../../../../utils/flowNodeCanonicalType";
import { canvasKindLabelFromNode } from "../../../../utils/palettePackageFactoryDraft";
import { canvasKindLabelForNodeId, parseStagingPayload } from "./model";
import packageStyles from "./ToolsMenuPackagePalette.module.css";
import { OVERLAY_TRIGGER_DELAY_PROPS, type ToolsMenuTooltipSide } from "./uiConstants";

export const PackageKindRow = memo(function PackageKindRow({
    desc,
    packageSectionKey,
    packagesPaletteEditMode = false,
    tooltipPlacement = "right",
}: {
    desc: NodeDescriptor;
    packageSectionKey?: string;
    packagesPaletteEditMode?: boolean;
    tooltipPlacement?: ToolsMenuTooltipSide;
}) {
    const { setNodes } = useReactFlow();
    const { removeKindFromPackageSection } = usePackagePalette();
    const showDelete = packagesPaletteEditMode && !!packageSectionKey;

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
            delay={OVERLAY_TRIGGER_DELAY_PROPS}
            overlay={
                <Tooltip>
                    {desc.label}
                    {desc.description ? ` — ${desc.description}` : ""}
                </Tooltip>
            }
        >
            <div className={packageStyles.packageKindRow}>
                <div
                    className={`${packageStyles.packageKindRowDrag}${showDelete ? ` ${packageStyles.packageKindRowDragEdit}` : ""}`}
                    draggable
                    onDragStart={(event) => {
                        event.dataTransfer.setData("application/reactflow", String(desc.id));
                        event.dataTransfer.effectAllowed = "move";
                    }}
                >
                    {showDelete ? (
                        <button
                            type="button"
                            className={packageStyles.packageKindDeleteBtn}
                            aria-label={`Remove ${desc.label} from package`}
                            title={`Remove ${desc.label} from package`}
                            onClick={(e) => {
                                e.stopPropagation();
                                removeKindFromPackageSection(packageSectionKey!, desc.id);
                            }}
                            onMouseDown={(e) => e.stopPropagation()}
                            onPointerDown={(e) => e.stopPropagation()}
                        >
                            <FontAwesomeIcon icon={faCircleMinus} aria-hidden />
                        </button>
                    ) : null}
                    <FontAwesomeIcon icon={desc.icon} className={packageStyles.packageKindDragIcon} />
                    {desc.badge ? (
                        <span className={packageStyles.packageKindDragBadge}>{desc.badge}</span>
                    ) : null}
                </div>
                <button
                    type="button"
                    className={packageStyles.packageKindRowMeta}
                    onClick={selectOnCanvas}
                    // title="Select nodes of this kind on the canvas"
                >
                    <span className={packageStyles.packageKindRowLabel}>{desc.label}</span>
                    <span className={packageStyles.packageKindCategoryChip}>{NODE_CATEGORY_SHORT_LABEL[desc.category]}</span>
                </button>
            </div>
        </OverlayTrigger>
    );
});

/** Trailing dashed drop target; each successful drop appends a staged row and this slot stays last. */
export const PackageCanvasDropSlot = memo(function PackageCanvasDropSlot({
    packageSectionKey,
}: {
    packageSectionKey: string;
}) {
    const [hover, setHover] = useState(false);
    const { stageCanvasNodeOnPackageSection } = usePackagePalette();
    const { getNodes } = useReactFlow();

    const labelForNodeId = useCallback(
        (nodeId: string) => canvasKindLabelForNodeId(nodeId, getNodes()),
        [getNodes],
    );

    const allowsMime = useCallback((dt: DataTransfer) => {
        return Array.from(dt.types).includes(PACKAGE_STAGING_MIME);
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
            const dropLabel = labelForNodeId(canvasNodeId);
            stageCanvasNodeOnPackageSection(packageSectionKey, canvasNodeId, {
                dedupeByLabel: dropLabel,
                labelForNodeId,
            });
        },
        [labelForNodeId, packageSectionKey, stageCanvasNodeOnPackageSection],
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
            className={`${packageStyles.packageCanvasDropSlot} ${hover ? packageStyles.packageCanvasDropSlotActive : ""}`}
            onDragOver={onDragOver}
            onDrop={onDrop}
            onDragEnter={onDragEnter}
            onDragLeave={onDragLeave}
            role="region"
            aria-label="Drop a canvas node here to attach it to this package while editing."
        >
            <span className={packageStyles.packageCanvasDropSlotInner}>Drop canvas node</span>
        </div>
    );
});

export const PackageStagedCanvasRow = memo(function PackageStagedCanvasRow({
    packageSectionKey,
    rowId,
    canvasNodeId,
}: {
    packageSectionKey: string;
    rowId: string;
    canvasNodeId: string;
}) {
    const { removeStagedRowFromSection } = usePackagePalette();
    const { setNodes } = useReactFlow();

    const label = useStore(
        useCallback((s: any) => {
            const n = s.nodeInternals?.get(canvasNodeId);
            if (!n?.data) return "Node";
            const t = String((n.data as { nodeType?: string }).nodeType ?? n.type ?? "");
            const desc = tryGetNodeDescriptor(t as NodeKindId);
            if (desc) return canvasKindLabelFromNode(n, desc);
            const tmpl = typeof (n.data as { templateName?: string }).templateName === "string"
                ? (n.data as { templateName?: string }).templateName!.trim()
                : "";
            return tmpl || t || canvasNodeId;
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
        <div className={packageStyles.packageStagedRow}>
            <span className={packageStyles.packageStagedRowGlyph} aria-hidden />
            <button type="button" className={packageStyles.packageStagedRowMeta} onClick={selectOnCanvas} title="Select this node on the canvas">
                <span className={packageStyles.packageStagedRowLabel}>{label}</span>
                <span className={packageStyles.packageStagedRowHint}>Canvas instance</span>
            </button>
            <button
                type="button"
                className={packageStyles.packageStagedRowRemove}
                title="Remove from package staging list"
                aria-label="Remove from package staging list"
                onClick={(e) => {
                    e.stopPropagation();
                    removeStagedRowFromSection(packageSectionKey, rowId);
                }}
            >
                <FontAwesomeIcon icon={faXmark} />
            </button>
        </div>
    );
});

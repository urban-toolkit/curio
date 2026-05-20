import React, { memo, useCallback, useState } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faCircleMinus, faXmark } from "@fortawesome/free-solid-svg-icons";
import { Tooltip, OverlayTrigger } from "react-bootstrap";
import { useReactFlow, useStore } from "reactflow";
import { NODE_CATEGORY_SHORT_LABEL } from "../../../../constants/nodeCategoryShortLabels";
import { PACK_STAGING_MIME } from "../../../../constants/packPaletteStaging";
import { tryGetNodeDescriptor } from "../../../../registry";
import { NodeDescriptor, NodeKindId } from "../../../../registry/types";
import { usePackPalette } from "../../../../providers/PackPaletteContext";
import { getFlowNodeCanonicalType } from "../../../../utils/flowNodeCanonicalType";
import { canvasKindLabelFromNode } from "../../../../utils/palettePackFactoryDraft";
import { canvasKindLabelForNodeId, parseStagingPayload } from "./model";
import packStyles from "./ToolsMenuPackPalette.module.css";
import { OVERLAY_TRIGGER_DELAY_PROPS, type ToolsMenuTooltipSide } from "./uiConstants";

export const PackKindRow = memo(function PackKindRow({
    desc,
    packSectionKey,
    packsPaletteEditMode = false,
    tooltipPlacement = "right",
}: {
    desc: NodeDescriptor;
    packSectionKey?: string;
    packsPaletteEditMode?: boolean;
    tooltipPlacement?: ToolsMenuTooltipSide;
}) {
    const { setNodes } = useReactFlow();
    const { removeKindFromPackSection } = usePackPalette();
    const showDelete = packsPaletteEditMode && !!packSectionKey;

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
            <div className={packStyles.packKindRow}>
                <div
                    className={`${packStyles.packKindRowDrag}${showDelete ? ` ${packStyles.packKindRowDragEdit}` : ""}`}
                    draggable
                    onDragStart={(event) => {
                        event.dataTransfer.setData("application/reactflow", String(desc.id));
                        event.dataTransfer.effectAllowed = "move";
                    }}
                >
                    {showDelete ? (
                        <button
                            type="button"
                            className={packStyles.packKindDeleteBtn}
                            aria-label={`Remove ${desc.label} from pack`}
                            title={`Remove ${desc.label} from pack`}
                            onClick={(e) => {
                                e.stopPropagation();
                                removeKindFromPackSection(packSectionKey!, desc.id);
                            }}
                            onMouseDown={(e) => e.stopPropagation()}
                            onPointerDown={(e) => e.stopPropagation()}
                        >
                            <FontAwesomeIcon icon={faCircleMinus} aria-hidden />
                        </button>
                    ) : null}
                    <FontAwesomeIcon icon={desc.icon} className={packStyles.packKindDragIcon} />
                    {desc.badge ? (
                        <span className={packStyles.packKindDragBadge}>{desc.badge}</span>
                    ) : null}
                </div>
                <button
                    type="button"
                    className={packStyles.packKindRowMeta}
                    onClick={selectOnCanvas}
                    // title="Select nodes of this kind on the canvas"
                >
                    <span className={packStyles.packKindRowLabel}>{desc.label}</span>
                    <span className={packStyles.packKindCategoryChip}>{NODE_CATEGORY_SHORT_LABEL[desc.category]}</span>
                </button>
            </div>
        </OverlayTrigger>
    );
});

/** Trailing dashed drop target; each successful drop appends a staged row and this slot stays last. */
export const PackCanvasDropSlot = memo(function PackCanvasDropSlot({
    packSectionKey,
}: {
    packSectionKey: string;
}) {
    const [hover, setHover] = useState(false);
    const { stageCanvasNodeOnPackSection } = usePackPalette();
    const { getNodes } = useReactFlow();

    const labelForNodeId = useCallback(
        (nodeId: string) => canvasKindLabelForNodeId(nodeId, getNodes()),
        [getNodes],
    );

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
            const dropLabel = labelForNodeId(canvasNodeId);
            stageCanvasNodeOnPackSection(packSectionKey, canvasNodeId, {
                dedupeByLabel: dropLabel,
                labelForNodeId,
            });
        },
        [labelForNodeId, packSectionKey, stageCanvasNodeOnPackSection],
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
            className={`${packStyles.packCanvasDropSlot} ${hover ? packStyles.packCanvasDropSlotActive : ""}`}
            onDragOver={onDragOver}
            onDrop={onDrop}
            onDragEnter={onDragEnter}
            onDragLeave={onDragLeave}
            role="region"
            aria-label="Drop a canvas node here to attach it to this pack while editing."
        >
            <span className={packStyles.packCanvasDropSlotInner}>Drop canvas node</span>
        </div>
    );
});

export const PackStagedCanvasRow = memo(function PackStagedCanvasRow({
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
        <div className={packStyles.packStagedRow}>
            <span className={packStyles.packStagedRowGlyph} aria-hidden />
            <button type="button" className={packStyles.packStagedRowMeta} onClick={selectOnCanvas} title="Select this node on the canvas">
                <span className={packStyles.packStagedRowLabel}>{label}</span>
                <span className={packStyles.packStagedRowHint}>Canvas instance</span>
            </button>
            <button
                type="button"
                className={packStyles.packStagedRowRemove}
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

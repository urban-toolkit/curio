import React, { useState, useEffect, useCallback, useMemo } from "react";
import ReactFlow, {
    ReactFlowProvider,
    Controls,
    Handle,
    Position,
    Node,
    Edge,
    NodeProps,
    EdgeProps,
    useReactFlow,
    useStore,
    getSmoothStepPath,
    BaseEdge,
} from "reactflow";
import "reactflow/dist/style.css";
import { NodeType } from "../../constants";
import { useProvenanceContext, NodeExecRecord } from "../../providers/ProvenanceProvider";
import { getLayoutedElements } from "../../utils/provenanceLayout";

type NodeProvenanceProps = {
    data: any;
    nodeType: NodeType;
    setCode: any;
    active?: boolean;
};

const EDGE_STYLE: React.CSSProperties = { stroke: "#222", strokeWidth: 2 };

// Floating edge: path is computed from actual RF-measured node dimensions
// (stored in nodeInternals after ResizeObserver fires), so it always connects
// exactly at the node boundary with no gap.
function ProvenanceEdge({ id, source, target, style }: EdgeProps) {
    const src = useStore(useCallback((s: any) => s.nodeInternals.get(source), [source]));
    const tgt = useStore(useCallback((s: any) => s.nodeInternals.get(target), [target]));

    if (!src?.width || !src?.height || !tgt?.width || !tgt?.height) return null;

    const [edgePath] = getSmoothStepPath({
        sourceX: src.positionAbsolute.x + src.width,
        sourceY: src.positionAbsolute.y + src.height / 2,
        sourcePosition: Position.Right,
        targetX: tgt.positionAbsolute.x,
        targetY: tgt.positionAbsolute.y + tgt.height / 2,
        targetPosition: Position.Left,
    });

    return <BaseEdge id={id} path={edgePath} style={style} />;
}

const HANDLE_STYLE: React.CSSProperties = { opacity: 0, pointerEvents: "none" };

function ExecNodeCard({ data }: NodeProps) {
    const { record, isSelected } = data as { record: NodeExecRecord; isSelected: boolean };
    const firstLine = record.code.split("\n").find((l: string) => l.trim().length > 0) || "";
    return (
        <div
            style={{
                padding: "6px 10px",
                background: isSelected ? "#1a73e8" : "#fff",
                color: isSelected ? "#fff" : "#333",
                border: isSelected ? "2px solid #0d47a1" : "1.5px solid #bbb",
                borderRadius: 6,
                fontSize: 11,
                minWidth: 140,
                maxWidth: 220,
                lineHeight: 2,
                cursor: "pointer",
                userSelect: "none",
            }}
        >
            <Handle type="target" position={Position.Left} style={HANDLE_STYLE} />
            <div style={{ fontWeight: 700, marginBottom: 2 }}>#{record.id}</div>
            <div style={{ opacity: 0.85 }}>
                In: {record.inputs.join(", ") || "—"} &nbsp;|&nbsp; Out: {record.outputs.join(", ") || "—"}
            </div>
            <div style={{ fontFamily: "monospace", marginTop: 2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {firstLine.slice(0, 30)}
            </div>
            <Handle type="source" position={Position.Right} style={HANDLE_STYLE} />
        </div>
    );
}

const nodeTypes = { execNode: ExecNodeCard };
const edgeTypes = { provenanceEdge: ProvenanceEdge };

function NodeProvenanceInner({ data, nodeType, setCode, active = false }: NodeProvenanceProps) {
    const { provenanceGraphNodes, setSelectedExec, selectedParentExecRef } = useProvenanceContext();
    const [selectedId, setSelectedId] = useState<number | null>(
        () => selectedParentExecRef.current[data.nodeId] ?? null
    );
    const { fitView } = useReactFlow();

    useEffect(() => {
        if (!active) return;
        const currentId = selectedParentExecRef.current[data.nodeId];
        if (currentId != null) setSelectedId(currentId);
        const id = setTimeout(() => fitView({ padding: 0.2 }), 300);
        return () => clearTimeout(id);
    }, [active]);

    const records: NodeExecRecord[] = provenanceGraphNodes[data.nodeId] || [];

    const { nodes: layoutedNodes, edges: layoutedEdges } = useMemo(() => {
        if (records.length === 0) return { nodes: [], edges: [] };

        const rfNodes: Node[] = records.map((r) => ({
            id: String(r.id),
            type: "execNode",
            position: { x: 0, y: 0 },
            data: { record: r, isSelected: r.id === selectedId },
        }));

        const rfEdges: Edge[] = records
            .filter((r) => r.parentId != null)
            .map((r) => ({
                id: `${r.parentId}->${r.id}`,
                source: String(r.parentId),
                target: String(r.id),
                type: "provenanceEdge",
                style: EDGE_STYLE,
            }));

        return getLayoutedElements(rfNodes, rfEdges, 220, 85, "LR");
    }, [records, selectedId]);

    const onNodeClick = useCallback(
        (_: any, node: Node) => {
            const id = parseInt(node.id, 10);
            const record = records.find((r) => r.id === id);
            if (!record) return;
            setSelectedId(id);
            setSelectedExec(data.nodeId, id);
            setCode(record.code);
        },
        [records, setSelectedExec, setCode, data.nodeId]
    );

    if (records.length === 0) {
        return (
            <div
                style={{
                    width: "100%",
                    height: "100%",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    color: "#999",
                    fontSize: 13,
                    background: "#e8e8e8",
                }}
            >
                No executions yet
            </div>
        );
    }

    // The wrapper carries the outer RF's default class names so that the outer RF's
    // ZoomPane (which checks event.target.closest('.nopan') / '.nowheel') and
    // useDrag (which checks hasSelector('.nodrag', outerNodeRef)) all find a match
    // and block outer-canvas interactions.
    //
    // The inner ReactFlow is given custom noPanClassName / noWheelClassName that
    // nothing inside the canvas has, so the inner RF's ZoomPane never finds a match
    // and inner panning + zooming work normally.
    return (
        <div
            className="nodrag nopan nowheel"
            style={{ width: "100%", height: "100%", position: "relative" }}
        >
            {active && (
                <ReactFlow
                    nodes={layoutedNodes}
                    edges={layoutedEdges}
                    nodeTypes={nodeTypes}
                    edgeTypes={edgeTypes}
                    onNodeClick={onNodeClick}
                    nodesDraggable={false}
                    nodesConnectable={false}
                    elementsSelectable={false}
                    zoomOnDoubleClick={false}
                    noPanClassName="inner-nopan"
                    noWheelClassName="inner-nowheel"
                    fitView
                    fitViewOptions={{ padding: 0.2 }}
                    style={{ background: "#e8e8e8" }}
                    proOptions={{ hideAttribution: true }}
                >
                    <Controls showInteractive={false} />
                </ReactFlow>
            )}
        </div>
    );
}

function NodeProvenance(props: NodeProvenanceProps) {
    return (
        <ReactFlowProvider>
            <NodeProvenanceInner {...props} />
        </ReactFlowProvider>
    );
}

export default NodeProvenance;

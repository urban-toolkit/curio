import React, { useState, useEffect, useRef } from "react";

// Bootstrap
import Button from "react-bootstrap/Button";
import "bootstrap/dist/css/bootstrap.min.css";
import { BoxType } from "../../constants";

// Editor
import Editor from "@monaco-editor/react";
import { useFlowContext } from "../../providers/FlowProvider";
import { useProvenanceContext } from "../../providers/ProvenanceProvider";
import { GraphCanvas } from "reagraph";

type BoxProvenanceProps = {
    data: any;
    boxType: BoxType;
    setCode: any;
};

function BoxProvenance({ data, boxType, setCode }: BoxProvenanceProps) {
    const { provenanceGraphBoxesRef } = useProvenanceContext();
    const provenanceBypass = useRef(false);

    const { workflowNameRef } = useFlowContext();

    const [provNodes, setProvNodes] = useState<{ id: string; label: string }[]>(
        []
    );
    const [provEdges, setProvEdges] = useState<
        { id: string; source: string; target: string; label: string }[]
    >([]);

    useEffect(() => {
        if (provenanceBypass.current) {
            let workflow_name = workflowNameRef.current;
            let activity_name = boxType + "_" + data.nodeId;

            if (provenanceGraphBoxesRef.current[workflow_name] == undefined)
                return;

            if (
                provenanceGraphBoxesRef.current[workflow_name][activity_name] ==
                undefined
            )
                return;

            let newNodes = [];
            let newEdges = [];

            for (
                let i = 0;
                i <
                provenanceGraphBoxesRef.current[workflow_name][activity_name]
                    .length;
                i++
            ) {
                let obj =
                    provenanceGraphBoxesRef.current[workflow_name][
                        activity_name
                    ][i];

                newNodes.push({
                    id: "n-" + i,
                    label:
                        "\n Inputs: " +
                        obj.inputs.join(", ") +
                        "\n Ouputs: " +
                        obj.outputs.join(", ") +
                        "\n Code: " +
                        obj.code.slice(0, 15),
                });

                if (i != 0)
                    newEdges.push({
                        id: i - 1 + "->" + i,
                        source: "n-" + (i - 1),
                        target: "n-" + i,
                        label: "Edge " + (i - 1) + "-" + i,
                    });
            }

            setProvNodes(newNodes);
            setProvEdges(newEdges);
        }

        provenanceBypass.current = true;
    }, [provenanceGraphBoxesRef.current]);

    const onNodeClick = (nodeData: any) => {
        let workflow_name = workflowNameRef.current;
        let activity_name = boxType + "_" + data.nodeId;

        let index = parseInt(nodeData.id.replace("n-", ""));

        setCode(
            provenanceGraphBoxesRef.current[workflow_name][activity_name][index]
                .code
        );
    };

    return (
        <div
            className={"nowheel nodrag"}
            style={{
                width: "100%",
                height: "100%",
                position: "relative",
                marginLeft: "auto",
                marginRight: "auto",
            }}
        >
            <GraphCanvas
                nodes={provNodes}
                edges={provEdges}
                onNodeClick={onNodeClick}
                layoutType={"treeTd2d"}
            />
        </div>
    );
}

export default BoxProvenance;

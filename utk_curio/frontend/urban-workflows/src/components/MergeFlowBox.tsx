import React, { useState, useEffect } from "react";
import { Handle, Position } from "reactflow";

import "bootstrap/dist/css/bootstrap.min.css";
import DescriptionModal from "./DescriptionModal";
import { BoxType } from "../constants";

import { Template, useTemplateContext } from "../providers/TemplateProvider";
import { BoxContainer } from "./styles";
import CSS from "csstype";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faCircleInfo } from "@fortawesome/free-solid-svg-icons";
import { useUserContext } from "../providers/UserProvider";

function MergeFlowBox({ data, isConnectable }: { data: any; isConnectable: boolean }) {
    const [output, setOutput] = useState<{ code: string; content: string }>({
        code: "",
        content: JSON.stringify({ data: [], dataType: "outputs" }),
    });
    const [templateData, setTemplateData] = useState<Template | any>({});
    const [showDescriptionModal, setDescriptionModal] = useState(false);

    const { editUserTemplate } = useTemplateContext();

    useEffect(() => {
        if (data.templateId != undefined) {
            setTemplateData({
                id: data.templateId,
                type: BoxType.MERGE_FLOW,
                name: data.templateName,
                description: data.description,
                accessLevel: data.accessLevel,
                code: data.defaultCode,
                custom: data.customTemplate,
            });
        }
    }, [data.templateId]);

    const setTemplateConfig = (template: Template) => {
        setTemplateData({ ...template });
    };

    const promptDescription = () => {
        setDescriptionModal(true);
    };

    const closeDescription = () => {
        setDescriptionModal(false);
    };

    const updateTemplate = (template: Template) => {
        setTemplateConfig(template);
        editUserTemplate(template);
    };

    const iconStyle: CSS.Properties = {
        fontSize: "1.5em",
        color: "#888787",
    };

    useEffect(() => {

        console.log("input", {...data.input});

        let newOutput: any = { data: [], dataType: "outputs" };

        if (Array.isArray(data.input)) {
            // Process primary input [0] then secondary input [1]
            const primaryInput = data.input[0];
            const secondaryInput = data.input[1];
            
            if (primaryInput !== undefined && primaryInput !== "") {
                newOutput.data.push(primaryInput);
            }
            
            if (secondaryInput !== undefined && secondaryInput !== "") {
                newOutput.data.push(secondaryInput);
            }
            
            // Only trigger output callback if we have at least one valid input
            if (newOutput.data.length > 0) {
                setOutput({ code: "success", content: newOutput });
                data.outputCallback(data.nodeId, newOutput);
            }
        }
    }, [data.input]);

    return (
        <>
            <Handle
                type="target"
                position={Position.Left}
                className={"handle_top_left"}
                id="in_1"
                isConnectable={isConnectable}
            />
            <Handle
                type="target"
                position={Position.Left}
                id="in_2"
                className={"handle_bottom_left"}
                isConnectable={isConnectable}
            />
            <Handle
                type="source"
                position={Position.Right}
                id="out"
                isConnectable={isConnectable}
            />
            <BoxContainer
                nodeId={data.nodeId}
                data={data}
                boxHeight={50}
                boxWidth={100}
                noContent={true}
                templateData={templateData}
                setOutputCallback={setOutput}
                updateTemplate={updateTemplate}
                promptDescription={promptDescription}
            >
                <DescriptionModal
                    nodeId={data.nodeId}
                    boxType={BoxType.MERGE_FLOW}
                    name={templateData.name}
                    description={templateData.description}
                    accessLevel={templateData.accessLevel}
                    show={showDescriptionModal}
                    handleClose={closeDescription}
                    custom={templateData.custom}
                />
            </BoxContainer>
        </>
    );
}

export default MergeFlowBox;

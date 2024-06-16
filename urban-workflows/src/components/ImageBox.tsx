import React, { useState, useEffect, useRef } from "react";
import { Handle, Position } from "reactflow";
import BoxEditor from "./editing/BoxEditor";

import { BoxContainer, buttonStyle } from "./styles";
import CSS from "csstype";

// Bootstrap
import "bootstrap/dist/css/bootstrap.min.css";
import { BoxType, VisInteractionType } from "../constants";
import { Template, useTemplateContext } from "../providers/TemplateProvider";
import DescriptionModal from "./DescriptionModal";
import TemplateModal from "./TemplateModal";
import { useUserContext } from "../providers/UserProvider";
import { useProvenanceContext } from "../providers/ProvenanceProvider";
import { useFlowContext } from "../providers/FlowProvider";
import { OutputIcon } from "./edges/OutputIcon";
import { InputIcon } from "./edges/InputIcon";

function ImageBox({ data, isConnectable }) {
    const [output, setOutput] = useState<{code: string, content: string}>({code: "", content: ""}); // stores the output produced by the last execution of this box
    const [code, setCode] = useState<string>("");
    const [templateData, setTemplateData] = useState<Template | any>({});

    const [interactions, _setInteractions] = useState<any>({}); // {signal: {type: point/interval, data: }} // if type point data contains list of object ids. If type is interval data is an object where each key is an attribute with intervals or lists
    const interactionsRef = React.useRef(interactions);
    const setInteractions = (data: any) => {
        interactionsRef.current = data;
        _setInteractions(data);
    };

    const [showTemplateModal, setShowTemplateModal] = useState(false);
    const [showDescriptionModal, setDescriptionModal] = useState(false);
    const dataInputBypass = useRef(false);

    const [images, setImages] = useState<string[]>([]);
    const [interacted, setInteracted] = useState<string[]>([]); // 0 -> not interacted. 1 -> interacted with

    const { boxExecProv } = useProvenanceContext();
    const { workflowName } = useFlowContext();

    useEffect(() => {
        if (data.templateId != undefined) {
            setTemplateData({
                id: data.templateId,
                type: BoxType.VIS_IMAGE,
                name: data.templateName,
                description: data.description,
                accessLevel: data.accessLevel,
                code: data.defaultCode,
                custom: data.customTemplate
            });
        }
    }, [data.templateId]);

    useEffect(() => {
        if (data.input != "" && dataInputBypass.current) {

            const formatDate = (date: Date) => {
                // Get individual date components
                const month = date.toLocaleString('default', { month: 'short' });
                const day = date.getDate();
                const year = date.getFullYear();
                const hours = date.getHours();
                const minutes = date.getMinutes();
                const seconds = date.getSeconds();
              
                // Format the string
                const formattedDate = `${month} ${day} ${year} ${hours}:${minutes}:${seconds}`;
              
                return formattedDate;
            }

            let startTime = formatDate(new Date());

            const getType = (inputs: any[]) => {
                let typesInput: string[] = [];
                
                for(const input of inputs){
                    let parsedInput = input;

                    if(typeof input == 'string')
                        parsedInput = JSON.parse(parsedInput);

                    if(parsedInput.dataType == "outputs"){
                        typesInput = typesInput.concat(getType(parsedInput.data));
                    }else{
                        typesInput.push(parsedInput.dataType);
                    }
                }
    
                return typesInput;
            }

            const mapTypes = (typesList: string[]) => {
        
                let mapTypes: any = {
                    "DATAFRAME": 0,
                    "GEODATAFRAME": 0,
                    "VALUE": 0,
                    "LIST": 0,
                    "JSON": 0
                };
    
                for(const typeValue of typesList){
                    if(typeValue == "int" || typeValue == "str" || typeValue == "float" || typeValue == "bool"){
                        mapTypes["VALUE"] = 1;
                    }else if(typeValue == "list"){
                        mapTypes["LIST"] = 1;
                    }else if(typeValue == "dict"){
                        mapTypes["JSON"] = 1;
                    }else if(typeValue == "dataframe"){
                        mapTypes["DATAFRAME"] = 1;
                    }else if(typeValue == "geodataframe"){
                        mapTypes["GEODATAFRAME"] = 1;
                    }
                }
    
                return mapTypes;
            }

            let typesInput: string[] = [];

            if(data.input != ""){
                typesInput = getType([data.input]);
            }
        
            let typesOuput: string[] = [...typesInput];

            boxExecProv(startTime, startTime, workflowName, BoxType.VIS_IMAGE+"_"+data.nodeId, mapTypes(typesInput), mapTypes(typesOuput), "");
            
            let parsedInput = JSON.parse(data.input);

            if(parsedInput.dataType != "dataframe"){
                alert("Image box can only receive dataframe");
                dataInputBypass.current = true;
                return;
            }

            parsedInput.data = JSON.parse(parsedInput.data);

            if(parsedInput.data.image_id == undefined || parsedInput.data.image_content == undefined){
                alert("Image needs to receive a dataframe with image_id and image_content columns.");
                dataInputBypass.current = true;
                return;
            }

            let newImages: string[] = [];
            let interacted: string[] = [];

            for(const key of Object.keys(parsedInput.data.image_content)){
                let iterator: string[] = [];

                if(Array.isArray(parsedInput.data.image_content[key])){
                    iterator = [...parsedInput.data.image_content[key]]
                }else{
                    iterator = [parsedInput.data.image_content[key]]
                }

                for(const base64ImageContent of iterator){
                    if(parsedInput.data.interacted != undefined){
                        interacted.push(parsedInput.data.interacted[key]);
                    }else{
                        interacted.push("0");
                    }
    
                    newImages.push('data:image/png;base64,' + base64ImageContent);
                }
            }

            setImages(newImages);
            setInteracted(interacted);

            // replicating input to the output
            setOutput({code: "success", content: data.input});
            data.outputCallback(data.nodeId, data.input);
        }

        dataInputBypass.current = true;

    }, [data.input]);

    const setTemplateConfig = (template: Template) => {
        setTemplateData({...template});
    }

    const closeModal = () => {
        setShowTemplateModal(false);
    }

    const promptDescription = () => {
        setDescriptionModal(true);
    }

    const closeDescription = () => {
        setDescriptionModal(false);
    }

    const clickImage = (index: number) => {

        let newObj: any = {};

        newObj["images_click"] = { type: VisInteractionType.POINT, data: [index], priority: 1, source: BoxType.VIS_IMAGE }

        setInteractions(newObj);
    }

    useEffect(() => {
        data.interactionsCallback(interactions, data.nodeId);
    }, [interactions]);

    const imageContainer: CSS.Properties = {
        display: "flex",
        flexWrap: "wrap",
        maxHeight: "100%",
        maxWidth: "100%",
        overflowY: "auto"
    }
    
    const imageStyle: CSS.Properties = {
        height: "auto", 
        margin: "5px" 
    }

    const selectedImageStyle: CSS.Properties = {
        height: "auto", 
        margin: "5px",
        border: "3px solid red"
    }

    const ContentComponent = ({ imageContainer, images, interacted, selectedImageStyle, imageStyle, clickImage }:{imageContainer: any, images: any, interacted: any, selectedImageStyle:any, imageStyle:any, clickImage:any}) => {
        return (
            <div className={"nowheel nodrag"} id={"imageBox_content_"+data.nodeId} style={imageContainer}>
                {images.map((src: string, index: number) => (
                    <div key={index} id={"imageBox_content_" + data.nodeId + "_" + index}>
                        {interacted != undefined && interacted.length == images.length && interacted[index] == "1" ?
                            <img src={src} width={50} height={50} style={selectedImageStyle} onClick={() => {clickImage(index)}}/> :
                            <img src={src} width={50} height={50} style={imageStyle} onClick={() => {clickImage(index)}}/>
                        }
                    </div>
                ))}
            </div>
        );
    };

    return (
        <>
            <Handle
                type="target"
                position={Position.Left}
                id="in"
                isConnectable={isConnectable}
            />
            <Handle
                type="source"
                position={Position.Right}
                id="out"
                isConnectable={isConnectable}
            />
            {/* Data flows in both ways */}
            <Handle
                type="source"
                position={Position.Top}
                id="in/out"
                isConnectable={isConnectable}
            />
            <BoxContainer nodeId={data.nodeId} data={data} templateData={templateData} setOutputCallback={setOutput} promptDescription={promptDescription} styles={{ paddingLeft: "16px" }}>
                <InputIcon type="1" />
                <DescriptionModal
                    nodeId={data.nodeId}
                    boxType={BoxType.VIS_IMAGE}
                    name={templateData.name}
                    description={templateData.description}
                    accessLevel={templateData.accessLevel}
                    show={showDescriptionModal}
                    handleClose={closeDescription}
                    custom={templateData.custom}
                />
                <BoxEditor
                    setSendCodeCallback={(_: any) => {}}
                    contentComponent={<ContentComponent imageContainer={imageContainer} images={images} interacted={interacted} selectedImageStyle={selectedImageStyle} imageStyle={imageStyle} clickImage={clickImage} />}
                    code={false}
                    grammar={false}
                    widgets={false}
                    provenance={false}
                    setOutputCallback={setOutput}
                    data={data}
                    output={output}
                    boxType={BoxType.VIS_IMAGE}
                    defaultValue={""}
                    readOnly={false}
                />
                <OutputIcon type="1" />
            </BoxContainer>
        </>
    );
}

export default ImageBox;

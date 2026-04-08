import React, { useState } from "react";
import CSS from "csstype";
import { useLLMContext } from "../../providers/LLMProvider";
import { NodeType } from "../../constants";
import ReactMarkdown from "react-markdown";

type NodeExplanationProps = {
    node_type: NodeType,
    code: string | undefined,
    current_input: string,
    current_output: string
}

export default function NodeExplanation({
    node_type,
    code,
    current_input,
    current_output
}: NodeExplanationProps
) {

    const [explanationText, setExplanationText] = useState('');
    const { openAIRequest } = useLLMContext();

    const generateExplanation = (node_type: NodeType, code: string | undefined, current_input: string, current_output: string) => {
        
        let node = {
            "id": "node1",
            "type": node_type,
            "content": code ? code : "",
            "current_input": current_input,
            "current_output": current_output
        }

        let text = JSON.stringify(node) + "\n\n" + "Your task as an assistant is to textually explain, in an high school level, what this box is doing. Include a lot of details and focus on explaning the content of the box and its possible role in the dataflow and opportunities to improve it. But do not include specific information about the trill structure like numeric ids. If errors are present help the users explain how they can be fixed (**DO NOT MENTION ANY PATH OR FILE NAME IN YOUR EXPLANATION**) **DO NOT PROVIDE EXPLANATIONS FOR THE EXAMPLE DATAFLOW. ALWAYS PRODUCE EXPLANATIONS FOR THE LAST NODE PROVIDED EVEN IF IT IS EMPTY**"

        openAIRequest("default_preamble", "single_box_explanation_prompt", text).then((response: any) => {
            console.log("Response:", response);

            setExplanationText(response.result);

        })
        .catch((error: any) => {
            console.error("Error:", error);
        });
    }
 
    return (
        <React.Fragment>

            {/* If no explanation, create brand new. Otherwise refresh current explanation. */}
            {explanationText == '' ? (
                <div className="nowheel nodrag" style={{ overflowY: "auto", fontSize: "12px", height: "100%", display: "flex", justifyContent: "center", alignItems: "center" }}>
                    <button style={{...buttonExplanation, }} onClick={() => {generateExplanation(node_type, code, current_input, current_output)}}>Generate explanation</button>
                </div>
            ) : <div className="nowheel nodrag" style={{ overflowY: "auto", fontSize: "10px", height: "100%", padding: "10px"}}>
                    <ReactMarkdown>{explanationText}</ReactMarkdown>
                    <button style={{...buttonExplanation, display: "flex", marginLeft: "auto", marginRight: "auto", fontSize: "12px"}} onClick={() => {generateExplanation(node_type, code, current_input, current_output)}}>Refresh explanation</button>
                </div>}

        </React.Fragment>
    )
}

const buttonExplanation: CSS.Properties = {
    border: "none",
    backgroundColor: "#1E1F23",
    color: "white",
    padding: "5px"
}

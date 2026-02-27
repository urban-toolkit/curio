import React, { useState, useEffect, useRef } from "react";
import JSONEditorReact from "./JSONEditorReact";
import { Button } from "react-bootstrap";
import { ICodeData } from "../../types";

import "./GrammarEditor.css";

// import schema from '../json-schema.json';

// declaring the types of the props
type GrammarEditorProps = {
    // setOutputCallback: any;
    output: ICodeData;
    nodeId: string;
    applyGrammar?: any;
    schema: any;
    replacedCode: string; // code with all marks resolved
    sendCodeToWidgets: any;
    replacedCodeDirty: boolean;
    defaultValue?: any;
    floatCode?: any;
    readOnly: boolean;
};

export default function GrammarEditor({
    // setOutputCallbackack,
    output,
    nodeId,
    applyGrammar,
    schema,
    replacedCode,
    sendCodeToWidgets,
    replacedCodeDirty,
    defaultValue,
    floatCode,
    readOnly,
}: GrammarEditorProps) {
    const [mode, setMode] = useState("code");

    const [activeSchema, setActiveSchema] = useState<any>(schema);

    const replacedCodeDirtyBypass = useRef(false);
    const defaultValueBypass = useRef(false);
    const readOnlyBypass = useRef(false);

    // const [grammar, _setCode] = useState('');

    // const grammarStateRef = useRef(grammar);
    // const setCode = (data: string) => {
    //     grammarStateRef.current = data;
    //     _setCode(data);
    // };

    const [grammar, _setGrammar] = useState("{}");

    const grammarRef = React.useRef(grammar);
    const setGrammar = (data: string) => {
        grammarRef.current = data;
        _setGrammar(data);
    };

    // useEffect(() => {
    // 	(document.getElementById('grammarApplyButton' + nodeId) as HTMLElement).addEventListener("click", function () {
    // 		sendCodeToWidgets(grammarRef.current);
    // 	});
    // }, []);

    useEffect(() => {
        if (defaultValueBypass.current) setGrammar(defaultValue);

        defaultValueBypass.current = true;
    }, [defaultValue]);

    useEffect(() => {
        if (floatCode != undefined) floatCode(grammar);
    }, [grammar]);

    useEffect(() => {
        if (replacedCode != "" &&
            replacedCodeDirtyBypass.current &&
            output.code == "exec" &&
            applyGrammar != undefined
        ) {
            applyGrammar(replacedCode);
        }

        replacedCodeDirtyBypass.current = true;
    }, [replacedCodeDirty]);

    useEffect(() => {
        if (readOnlyBypass.current) {
            let textarea = document.querySelector(
                "#vega-editor_" + nodeId + " textarea"
            ) as HTMLTextAreaElement;
            textarea.disabled = readOnly;
        }

        readOnlyBypass.current = true;
    }, [readOnly]);

    const updateGrammarContent = (grammarObj: string, readOnly: boolean) => {
        if (!readOnly) setGrammar(grammarObj);
    };

    const onModeChange = (mode: string) => {
        setMode(mode);
    };

    const modes = ["code"];

    // schema={activeSchema}
    // schemaRefs={{"categories": schema_categories}}

    return (
        <React.Fragment>
            <div
                id={"vega-editor_" + nodeId}
                className="my-editor nowheel nodrag"
                style={{ overflowY: "auto", fontSize: "24px", height: "100%" }}
            >
                <JSONEditorReact
                    nodeId={nodeId}
                    content={grammar}
                    mode={mode}
                    modes={modes}
                    onChangeText={(grammarObj: string) => {
                        updateGrammarContent(grammarObj, readOnly);
                    }}
                    onModeChange={onModeChange}
                    allowSchemaSuggestions={true}
                    indentation={2}
                    schema={activeSchema}
                />
            </div>
            {/* <div className="d-flex align-items-center justify-content-left" style={{ overflow: "auto", height: "75px" }}>
				<Button variant="primary" id={'grammarApplyButton' + nodeId} style={{ marginLeft: "10px", marginRight: "20px", height: "54px" }}>Apply Grammar</Button>
			</div> */}
        </React.Fragment>
    );
}

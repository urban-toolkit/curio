import React, { useState, useEffect, useRef } from "react";
import Editor from "@monaco-editor/react";
import { ICodeData } from "../../types";
import { useCollaborationContext } from "../../providers/CollaborationProvider";

type GrammarEditorProps = {
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
    const [grammar, _setGrammar] = useState(
        typeof defaultValue === "string" ? defaultValue : "{}"
    );
    const grammarRef = useRef(grammar);
    const setGrammar = (data: string) => {
        grammarRef.current = data;
        _setGrammar(data);
    };

    const { requestCodeChange } = useCollaborationContext();
    const requestCodeChangeRef = useRef(requestCodeChange);
    useEffect(() => { requestCodeChangeRef.current = requestCodeChange; }, [requestCodeChange]);

    const replacedCodeDirtyBypass = useRef(false);

    useEffect(() => {
        if (defaultValue != undefined && defaultValue !== grammarRef.current) {
            setGrammar(defaultValue);
        }
    }, [defaultValue]);

    useEffect(() => {
        if (floatCode != undefined) floatCode(grammar);
    }, [grammar]);

    useEffect(() => {
        if (
            replacedCode != "" &&
            replacedCodeDirtyBypass.current &&
            output.code == "exec" &&
            applyGrammar != undefined
        ) {
            applyGrammar(replacedCode);
        }
        replacedCodeDirtyBypass.current = true;
    }, [replacedCodeDirty]);

    const updateGrammarContent = (value: string, readOnly: boolean) => {
        if (!readOnly) setGrammar(value);
    };

    const commitGrammarChange = () => {
        if (!readOnly) requestCodeChangeRef.current(nodeId, grammarRef.current);
    };

    return (
        <div
            id={"vega-editor_" + nodeId}
            className="my-editor nowheel nodrag"
            style={{ height: "100%" }}
        >
            <Editor
                height="100%"
                language="json"
                theme="vs"
                path={`grammar-${nodeId}.json`}
                value={grammar}
                onChange={(value) => updateGrammarContent(value ?? "{}", readOnly)}
                onMount={(editor) => {
                    editor.onDidBlurEditorText(commitGrammarChange);
                }}
                options={{
                    fontSize: 13,
                    fontFamily: "'Source Code Pro', Consolas, 'Courier New', monospace",
                    minimap: { enabled: false },
                    readOnly: readOnly,
                    scrollBeyondLastLine: false,
                    formatOnType: true,
                    autoClosingBrackets: "always",
                }}
            />
        </div>
    );
}

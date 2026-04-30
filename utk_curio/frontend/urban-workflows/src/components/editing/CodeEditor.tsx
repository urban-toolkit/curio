import React, { useState, useEffect, useRef } from "react";

import "bootstrap/dist/css/bootstrap.min.css";
import { NodeType } from "../../constants";

// Editor
import Editor from "@monaco-editor/react";
import { useFlowContext } from "../../providers/FlowProvider";
import { useProvenanceContext } from "../../providers/ProvenanceProvider";
import { ICodeData } from "../../types";

type CodeEditorProps = {
    setOutputCallback: any;
    data: any;
    output: ICodeData;
    nodeType: NodeType;
    replacedCode: string; // code with all marks resolved
    sendCodeToWidgets: any;
    replacedCodeDirty: boolean;
    readOnly: boolean;
    defaultValue?: any;
    floatCode?: any;
};

function CodeEditor({
    setOutputCallback,
    data,
    output,
    nodeType,
    replacedCode,
    sendCodeToWidgets,
    replacedCodeDirty,
    readOnly,
    defaultValue,
    floatCode,
}: CodeEditorProps) {
    const [code, setCode] = useState<string>(""); // code with all original markers
    const [execCount, setExecCount] = useState<number>(0);

    const { workflowNameRef, markNodeExecuted, markNodeStale, signalNodeExecDone } = useFlowContext();
    const { nodeExecProv } = useProvenanceContext();

    const replacedCodeDirtyBypass = useRef(false);
    const defaultValueBypass = useRef(false);

    // @ts-ignore
    const handleCodeChange = (value, event) => {
        setCode(value);
        markNodeStale(data.nodeId);
    };

    useEffect(() => {
        if (defaultValue != undefined && defaultValueBypass.current) {
            setCode(defaultValue);
            sendCodeToWidgets(defaultValue); // will resolve markers for templated boxes
        }

        defaultValueBypass.current = true;
    }, [defaultValue]);

    useEffect(() => {
        if (floatCode != undefined) floatCode(code);
    }, [code]);

    useEffect(() => {
        if (output.code === "success" || output.code === "error") {
            setExecCount(prev => prev + 1);
        }
    }, [output.code]);

    const processExecutionResult = (result: any) => {
        const hasOutput = result.output?.path !== "";

        if (hasOutput) {
            let outputContent = "stdout:\n" + result.stdout.slice(0, 100);
            if (result.stderr) outputContent += "\nstderr:\n" + result.stderr;
            outputContent += "\nSaved to file: " + result.output.path;
            setOutputCallback({ code: "success", content: outputContent });
            data.outputCallback(data.nodeId, result.output);
            markNodeExecuted(data.nodeId);
        } else {
            setOutputCallback({ code: "error", content: result.stderr });
            signalNodeExecDone(data.nodeId);
        }
    };

    // marks were resolved and new code is available
    useEffect(() => {
        if (!replacedCodeDirtyBypass.current) {
            replacedCodeDirtyBypass.current = true;
            return;
        }
        if (output.code !== "exec") return;
        if (replacedCode === "") {
            setOutputCallback({ code: "error", content: "No code to execute" });
            return;
        }
        const isJsNode = nodeType === NodeType.JS_COMPUTATION || nodeType === NodeType.AUTK_DB;
        const interpreter = (isJsNode && data.jsInterpreter)
            ? data.jsInterpreter
            : data.pythonInterpreter;
        interpreter.interpretCode(
            code,
            replacedCode,
            data.input,
            data.inputTypes,
            processExecutionResult,
            nodeType,
            data.nodeId,
            workflowNameRef.current,
            nodeExecProv
        );
    }, [replacedCodeDirty]);

    useEffect(() => {
        // Save a reference to the original ResizeObserver
        const OriginalResizeObserver = window.ResizeObserver;

        // @ts-ignore
        window.ResizeObserver = function (callback) {
            const wrappedCallback = (entries: any, observer: any) => {
                window.requestAnimationFrame(() => {
                    callback(entries, observer);
                });
            };

            // Create an instance of the original ResizeObserver
            // with the wrapped callback
            return new OriginalResizeObserver(wrappedCallback);
        };

        // Copy over static methods, if any
        for (let staticMethod in OriginalResizeObserver) {
            if (
                Object.prototype.hasOwnProperty.call(
                    OriginalResizeObserver,
                    staticMethod
                )
            ) {
                // @ts-ignore
                window.ResizeObserver[staticMethod] = OriginalResizeObserver[staticMethod];
            }
        }
    }, []);

    const execLabel = output.code === "exec" ? "[*]:" : execCount > 0 ? `[${execCount}]:` : "[ ]:";
    const outputText = output.code === "exec"
        ? "Running..."
        : typeof output.content === "string" && output.content
            ? output.content
            : "No output yet";

    return (
        <div className="nowheel nodrag" style={{ height: "100%", display: "flex", flexDirection: "column", backgroundColor: "#fff" }}>
            <div style={{ flex: 2, minHeight: 0 }}>
                <Editor
                    height="100%"
                    language={(nodeType === NodeType.JS_COMPUTATION || nodeType === NodeType.AUTK_DB) ? "javascript" : "python"}
                    theme="vs"
                    value={code}
                    onChange={handleCodeChange}
                    options={{
                        // @ts-ignore
                        inlineSuggest: true,
                        fontSize: 13,
                        fontFamily: "'Source Code Pro', Consolas, 'Courier New', monospace",
                        formatOnType: true,
                        autoClosingBrackets: "always",
                        minimap: { enabled: false },
                        readOnly: readOnly,
                        scrollBeyondLastLine: false,
                    }}
                />
            </div>
            <div
                className="nowheel nodrag"
                style={{
                    flex: 1,
                    minHeight: 0,
                    overflowY: "auto",
                    backgroundColor: "#f7f7f7",
                    borderTop: "1px solid #e0e0e0",
                    padding: "4px 8px",
                    fontSize: "11px",
                    fontFamily: "'Source Code Pro', Consolas, 'Courier New', monospace",
                    whiteSpace: "pre-wrap",
                    color: output.code === "error" ? "#c0392b" : "#333",
                    userSelect: "text",
                    cursor: "text",
                }}
            >
                <span style={{ color: "#303F9F", fontWeight: "bold", marginRight: "6px" }}>{execLabel}</span>
                {outputText}
            </div>
        </div>
    );
}

export default CodeEditor;

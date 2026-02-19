import React, { useState, useEffect, useRef } from "react";

// Bootstrap
import Button from "react-bootstrap/Button";
import "bootstrap/dist/css/bootstrap.min.css";
import { BoxType } from "../../constants";

// Editor
import Editor from "@monaco-editor/react";
import { useFlowContext } from "../../providers/FlowProvider";
import { useProvenanceContext } from "../../providers/ProvenanceProvider";
import { ICodeData } from "../../types";

type CodeEditorProps = {
    setOutputCallback: any;
    data: any;
    output: ICodeData;
    boxType: BoxType;
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
    boxType,
    replacedCode,
    sendCodeToWidgets,
    replacedCodeDirty,
    readOnly,
    defaultValue,
    floatCode,
}: CodeEditorProps) {
    const [code, setCode] = useState<string>(""); // code with all original markers

    const { workflowNameRef } = useFlowContext();
    const { boxExecProv } = useProvenanceContext();

    const replacedCodeDirtyBypass = useRef(false);
    const defaultValueBypass = useRef(false);

    // @ts-ignore
    const handleCodeChange = (value, event) => {
        setCode(value);
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

    const processExecutionResult = (result: any) => {
        let outputContent = "";
        outputContent += "stdout:\n"+result.stdout.slice(0, 100);
        outputContent += "\nstderr:\n"+result.stderr;

        // outputContent += "\nnode output:\n";
        // if (outputContent.length > 100) {
        //     outputContent += result.codeOut.slice(0, 100) + "...";
        // }
        // else {
        //     outputContent += result.codeOut;
        // }

        outputContent += "\nSaved to file: "+result.output.path;

        setOutputCallback({ code: "success", content: outputContent });

        if (result.stderr == "") {
            // No error in the execution
            data.outputCallback(data.nodeId, result.output);
        } else {
            setOutputCallback({ code: "error", content: result.stderr });
        }
    };

    // marks were resolved and new code is available
    useEffect(() => {
        if (
            replacedCode != "" &&
            replacedCodeDirtyBypass.current &&
            output.code == "exec"
        ) {
            // the code was executing and not only resolving widgets
            // console.log(data);
            data.pythonInterpreter.interpretCode(
                code,
                replacedCode,
                data.input,
                data.inputTypes,
                processExecutionResult,
                boxType,
                data.nodeId,
                workflowNameRef.current,
                boxExecProv
            );
        }

        replacedCodeDirtyBypass.current = true;
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

    return (
        <div className={"nowheel nodrag"} style={{ height: "100%" }}>
            <Editor
                language="python"
                theme="vs-dark"
                value={code}
                onChange={handleCodeChange}
                options={{
                    // @ts-ignore
                    inlineSuggest: true,
                    fontSize: 8,
                    formatOnType: true,
                    // @ts-ignore
                    autoClosingBrackets: true,
                    minimap: { enabled: false },
                    readOnly: readOnly,
                }}
            />
            {/* <div
                className="nowheel"
                style={{ width: "100%", maxHeight: "200px", overflowY: "scroll" }}
            >
                {output == "success" ? "Done" : output == "exec" ? "Executing..." : output != "" ? "Error: "+output : ""}
            </div> */}
            {/* <Button
                as="a"
                variant="primary"
                onClick={() => {
                    setOutputCallback("exec");
                    sendCodeToWidgets(code); // will resolve markers
                }}
            >
                Run code
          </Button> */}
        </div>
    );
}

export default CodeEditor;

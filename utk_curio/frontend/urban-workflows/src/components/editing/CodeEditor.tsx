import React, { useState, useEffect, useRef } from "react";

import "bootstrap/dist/css/bootstrap.min.css";
import { NodeType } from "../../constants";
import { NodeKindId } from "../../registry/types";

// Editor
import Editor from "@monaco-editor/react";
import { useFlowContext } from "../../providers/FlowProvider";
import { useProvenanceContext } from "../../providers/ProvenanceProvider";
import { ICodeData } from "../../types";

type CodeEditorProps = {
    setOutputCallback: any;
    data: any;
    output: ICodeData;
    nodeType: NodeKindId;
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
    const outputRef = useRef<HTMLDivElement>(null);

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

        // result.stdout is list[str] from the sandbox; join with newlines so
        // multi-line autkdb output is readable instead of comma-coerced. Cap
        // at the last 4000 chars so a runaway log loop can't lock the panel,
        // and show the tail since errors usually surface there.
        const STDOUT_CAP = 4000;
        const stdoutLines: string[] = Array.isArray(result.stdout)
            ? result.stdout
            : (result.stdout ? [String(result.stdout)] : []);
        let stdoutText = stdoutLines.join("\n");
        let stdoutTruncated = false;
        if (stdoutText.length > STDOUT_CAP) {
            stdoutText = stdoutText.slice(-STDOUT_CAP);
            stdoutTruncated = true;
        }
        const stdoutBlock = stdoutText
            ? "stdout:\n" + (stdoutTruncated
                ? `... [truncated to last ${STDOUT_CAP} chars]\n` + stdoutText
                : stdoutText)
            : "";

        if (hasOutput) {
            let outputContent = stdoutBlock;
            if (result.stderr) {
                outputContent += (outputContent ? "\n" : "") + "stderr:\n" + result.stderr;
            }
            outputContent += (outputContent ? "\n" : "") + "Saved to file: " + result.output.path;
            setOutputCallback({ code: "success", content: outputContent });
            data.outputCallback(data.nodeId, result.output);
            markNodeExecuted(data.nodeId);
        } else {
            let errorContent = "";
            if (stdoutBlock) errorContent += stdoutBlock + "\n";
            errorContent += result.stderr || "(no stderr)";
            setOutputCallback({ code: "error", content: errorContent });
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

    // Confine drag-selections that start in the output box to the box itself.
    // We drive the selection manually on every mousemove (anchor at the initial
    // click, focus at the cursor clamped to the box's bounding rect), which
    // overrides the browser's native selection extension so the range never
    // bleeds into other nodes.
    useEffect(() => {
        const el = outputRef.current;
        if (!el) return;

        const caretFromPoint = (x: number, y: number): { node: Node; offset: number } | null => {
            const doc: any = document;
            if (typeof doc.caretRangeFromPoint === "function") {
                const r: Range | null = doc.caretRangeFromPoint(x, y);
                return r ? { node: r.startContainer, offset: r.startOffset } : null;
            }
            if (typeof doc.caretPositionFromPoint === "function") {
                const p = doc.caretPositionFromPoint(x, y);
                return p ? { node: p.offsetNode, offset: p.offset } : null;
            }
            return null;
        };

        const onMouseDown = (e: MouseEvent) => {
            if (e.button !== 0) return;
            if (!(e.target instanceof Node) || !el.contains(e.target)) return;

            const anchor = caretFromPoint(e.clientX, e.clientY);
            if (!anchor || !el.contains(anchor.node)) return;

            // Stop the browser from starting its own drag-select; we drive
            // the selection manually so it can't extend outside the box.
            e.preventDefault();

            const sel = window.getSelection();
            sel?.removeAllRanges();
            sel?.setBaseAndExtent(anchor.node, anchor.offset, anchor.node, anchor.offset);

            const onMouseMove = (ev: MouseEvent) => {
                ev.preventDefault();
                const rect = el.getBoundingClientRect();
                const cx = Math.max(rect.left + 1, Math.min(rect.right - 1, ev.clientX));
                const cy = Math.max(rect.top + 1, Math.min(rect.bottom - 1, ev.clientY));
                const focus = caretFromPoint(cx, cy);
                if (!focus || !el.contains(focus.node)) return;
                window.getSelection()?.setBaseAndExtent(anchor.node, anchor.offset, focus.node, focus.offset);
            };

            const onMouseUp = () => {
                document.removeEventListener("mousemove", onMouseMove, true);
                document.removeEventListener("mouseup", onMouseUp, true);
            };

            document.addEventListener("mousemove", onMouseMove, true);
            document.addEventListener("mouseup", onMouseUp, true);
        };

        el.addEventListener("mousedown", onMouseDown);
        return () => {
            el.removeEventListener("mousedown", onMouseDown);
        };
    }, []);

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
        <div className="nowheel nodrag" style={{ height: "100%", display: "flex", flexDirection: "column", backgroundColor: "#fff", userSelect: "none" }}>
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
                ref={outputRef}
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

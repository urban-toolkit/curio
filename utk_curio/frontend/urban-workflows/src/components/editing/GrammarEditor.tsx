import React, { useState, useEffect, useRef } from "react";
import Editor, { Monaco } from "@monaco-editor/react";
import { ICodeData } from "../../types";
import { useCollab, CodeProposal } from "../../providers/CollaborationProvider";

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
    const [grammar, _setGrammar] = useState("{}");
    const grammarRef = useRef(grammar);
    const setGrammar = (data: string) => {
        grammarRef.current = data;
        _setGrammar(data);
    };

    const replacedCodeDirtyBypass = useRef(false);
    const defaultValueBypass = useRef(false);

    const collab = useCollab();
    const collabRef = useRef(collab);
    collabRef.current = collab;
    const baselineRef = useRef<string>("{}");

    useEffect(() => {
        if (defaultValueBypass.current) {
            setGrammar(defaultValue);
            baselineRef.current = defaultValue;
        }
        defaultValueBypass.current = true;
    }, [defaultValue]);

    // Collaboration: propose grammar change on blur, receive applied changes.
    const proposeOnBlur = () => {
        const c = collabRef.current;
        if (!c.enabled || !c.connected) return;
        if (c.users.length <= 1) return;
        const local = grammarRef.current;
        const baseline = baselineRef.current;
        if (local === baseline) return;
        c.requestCodeChange(nodeId, baseline, local, "grammar");
    };

    const handleEditorMount = (editor: any, monaco: Monaco) => {
        // Vega-Lite specs carry `$schema: "https://.../v6.json"` (~2 MB). Monaco's
        // built-in JSON support will fetch and validate against that URL on first
        // tab-switch into the editor, which freezes the main thread while it
        // resolves the schema graph. Disable URL fetching and clear the schema
        // list so Monaco only does the cheap structural JSON parse.
        try {
            monaco.languages.json.jsonDefaults.setDiagnosticsOptions({
                validate: true,
                enableSchemaRequest: false,
                schemas: [],
            });
        } catch {
            // Defensive: older Monaco builds without languages.json — no-op.
        }
        editor.onDidBlurEditorText(proposeOnBlur);
    };

    useEffect(() => {
        if (!collab.enabled) return;
        const unsub = collab.onRemote("code_change_applied", (payload) => {
            const prop = payload as CodeProposal;
            if (!prop || prop.nodeId !== nodeId || prop.kind !== "grammar") return;
            if (collab.currentUserId != null &&
                prop.proposed_by?.user_id === collab.currentUserId) {
                baselineRef.current = prop.newValue;
                return;
            }
            setGrammar(prop.newValue);
            baselineRef.current = prop.newValue;
        });
        return unsub;
    }, [collab.enabled, collab.onRemote, collab.currentUserId, nodeId]);

    const pendingProposal = collab.proposals.find(
        (p) => p.nodeId === nodeId && p.kind === "grammar",
    );
    const proposalIsMine = Boolean(
        pendingProposal && collab.currentUserId != null &&
        pendingProposal.proposed_by?.user_id === collab.currentUserId,
    );

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

    return (
        <div
            id={"vega-editor_" + nodeId}
            className="my-editor nowheel nodrag"
            style={{ height: "100%", display: "flex", flexDirection: "column" }}
        >
            {pendingProposal && (
                <div
                    style={{
                        padding: "4px 8px",
                        background: proposalIsMine ? "#fff8e1" : "#e3f2fd",
                        borderBottom: "1px solid #ccc",
                        fontSize: 11,
                        display: "flex",
                        alignItems: "center",
                        gap: 6,
                    }}
                >
                    <span style={{ flex: 1 }}>
                        {proposalIsMine
                            ? `Awaiting approval (${pendingProposal.approvals.length}).`
                            : `${pendingProposal.proposed_by?.username || "Peer"} proposed a grammar change.`}
                    </span>
                    {!proposalIsMine && (
                        <>
                            <button
                                type="button"
                                onClick={() => collab.approveCodeChange(pendingProposal.id)}
                                style={{ padding: "1px 8px", fontSize: 11 }}
                            >
                                Approve
                            </button>
                            <button
                                type="button"
                                onClick={() => collab.rejectCodeChange(pendingProposal.id)}
                                style={{ padding: "1px 8px", fontSize: 11 }}
                            >
                                Reject
                            </button>
                        </>
                    )}
                </div>
            )}
            <div style={{ flex: 1, minHeight: 0 }}>
                <Editor
                    height="100%"
                    language="json"
                    theme="vs"
                    path={`grammar-${nodeId}.json`}
                    value={grammar}
                    onChange={(value) => updateGrammarContent(value ?? "{}", readOnly)}
                    onMount={handleEditorMount}
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
        </div>
    );
}

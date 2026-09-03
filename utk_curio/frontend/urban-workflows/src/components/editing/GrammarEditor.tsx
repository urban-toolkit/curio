import React, { useState, useEffect, useRef } from "react";
import Editor, { Monaco } from "@monaco-editor/react";
import { ICodeData } from "../../types";
import { useCollab, CodeProposal } from "../../providers/CollaborationProvider";
import { useMonacoExternalValue } from "../../hook/useMonacoExternalValue";
import { useFlowContext } from "../../providers/FlowProvider";
import { registerRunNodeAction } from "./runNodeMonacoAction";

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

    const collab = useCollab();
    const collabRef = useRef(collab);
    collabRef.current = collab;

    // The Monaco model is the source of truth while the user types; `grammar`
    // only mirrors it. Content flows INTO the editor exclusively through this
    // hook: `defaultValue` is applied only when a genuinely new external
    // string arrives, and `undefined`/stale flips are ignored - the previous
    // unconditional `setGrammar(defaultValue)` effect is what reset a fresh
    // Autark node to the default spec while typing. That subsumes the older
    // `!= undefined` guard this effect used to carry (#157). `baselineRef` is
    // the as-loaded grammar the collab blur-diff compares against.
    const { baselineRef, applyValue, attachEditor } = useMonacoExternalValue({
        externalValue: defaultValue,
        initialContent: "{}",
        onExternalApply: (value) => {
            setGrammar(value);
            // Same call CodeEditor makes, and for the same reason: WidgetsEditor
            // only recomputes its marker list when `markersDirty` toggles, and
            // this is the only thing that toggles it outside a run. Without it a
            // grammar spec's `[!! ... !!]` markers render no widgets until the
            // node has been played once.
            sendCodeToWidgets(value);
        },
    });

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

    // onMount fires once, so the action reads the CURRENT play function through
    // a ref rather than capturing the first render's (#223).
    const { playNodesUpTo } = useFlowContext();
    const runNodeRef = useRef<() => void>(() => {});
    runNodeRef.current = () => playNodesUpTo(nodeId);

    const handleEditorMount = (editor: any, monaco: Monaco) => {
        // Vega-Lite specs carry `$schema: "https://.../v6.json"` (~2 MB). Monaco's
        // built-in JSON support will fetch and validate against that URL on first
        // tab-switch into the editor, which freezes the main thread while it
        // resolves the schema graph. Disable URL fetching and clear the schema
        // list so Monaco only does the cheap structural JSON parse.
        try {
            // monaco-editor's core typings stub `languages.json` as
            // `{ deprecated: true }`; the real declarations ship with the JSON
            // language contribution, whose .d.ts is an empty `export {}`. The
            // API exists at runtime once that contribution is loaded, so this
            // states the one call being made rather than reaching for `any`.
            const jsonLanguage = monaco.languages.json as unknown as {
                jsonDefaults: {
                    setDiagnosticsOptions(options: {
                        validate?: boolean;
                        enableSchemaRequest?: boolean;
                        schemas?: unknown[];
                    }): void;
                };
            };
            jsonLanguage.jsonDefaults.setDiagnosticsOptions({
                validate: true,
                enableSchemaRequest: false,
                schemas: [],
            });
        } catch {
            // Defensive: older Monaco builds without languages.json — no-op.
        }
        attachEditor(editor);
        editor.onDidBlurEditorText(proposeOnBlur);
        // Same chord as the code editor, so a grammar node runs the way a
        // Python one does (#223).
        registerRunNodeAction(editor, monaco, () => runNodeRef.current);
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
            applyValue(prop.newValue); // editor + baseline (cursor-preserving)
            setGrammar(prop.newValue);
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
        // Strings only: floating a non-string (the old reset chain produced
        // `undefined`) poisons ``nodeState.code``/``data.code`` downstream.
        if (floatCode != undefined && typeof grammar === "string") floatCode(grammar);
    }, [grammar]);

    useEffect(() => {
        if (
            replacedCode != "" &&
            replacedCodeDirtyBypass.current &&
            output.code == "exec" &&
            applyGrammar != undefined
        ) {
            // Catch, don't float (#201). An escaped rejection reaches
            // `window` as `unhandledrejection`, which webpack-dev-server's
            // runtime-error overlay listens for - so one throw inside the
            // grammar took the whole screen in development.
            void Promise.resolve(applyGrammar(replacedCode)).catch((err) => {
                console.error("[GrammarEditor] applyGrammar failed:", err);
            });
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
                {/* Uncontrolled on purpose: a per-keystroke `value` round-trip
                    lets a render that lands with a stale string do a full-model
                    replace — resetting content and throwing the cursor to the
                    end (dev/70). External content arrives via attachEditor /
                    applyValue in useMonacoExternalValue instead. */}
                <Editor
                    height="100%"
                    language="json"
                    theme="vs"
                    path={`grammar-${nodeId}.json`}
                    defaultValue="{}"
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

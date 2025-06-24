import JSONEditor, { JSONEditorMode } from "jsoneditor";
// import '../../node_modules/jsoneditor/dist/jsoneditor.min.css';
import "../../../node_modules/jsoneditor/dist/jsoneditor.min.css";

import React, { Component, useEffect, useRef } from "react";

// declaring the types of the props
type JSONEditorReactProps = {
    nodeId: string;
    content: any;
    schema?: any;
    schemaRefs?: any;
    mode: JSONEditorMode;
    modes: string[];
    onChangeText: any;
    onModeChange: any;
    allowSchemaSuggestions: boolean;
    indentation: number;
};

export default function JSONEditorReact({
    nodeId,
    content,
    schema,
    schemaRefs,
    mode,
    modes,
    onChangeText,
    onModeChange,
    allowSchemaSuggestions,
    indentation,
}: JSONEditorReactProps) {
    // const refContainer = useRef<string | null>(null);
    const refEditor = useRef<JSONEditor | null>(null);

    useEffect(() => {
        // create the editor
        const container = document.getElementById("grammarJsonEditor" + nodeId);

        const options = {
            schema: schema,
            schemaRefs: schemaRefs,
            mode: mode,
            indentation: indentation,
            modes: modes as JSONEditorMode[],
            onModeChange: onModeChange,
            allowSchemaSuggestions: allowSchemaSuggestions,
            onChangeText: onChangeText,
        };

        refEditor.current = new JSONEditor(container as HTMLElement, options);
        refEditor.current.setText(content);

        // if('json' in content){
        //   refEditor.current.set(content.json);
        // }

        // if('text' in content){
        //   refEditor.current.setText(content.text);
        // }
    }, []);

    useEffect(() => {
        if (refEditor.current) {
            refEditor.current.updateText(content);
            //   if('json' in content){
            //     refEditor.current.update(content.json);
            //   }

            //   if('text' in content){
            //     refEditor.current.updateText(content.text);
            //   }
        }
    }, [content]);

    useEffect(() => {
        if (refEditor.current) {
            refEditor.current.setMode(mode);
        }
    }, [mode]);

    useEffect(() => {
        if (refEditor.current) {
            refEditor.current.setSchema(schema);
        }
    }, [schema]);

    return (
        <div id={"grammarJsonEditor" + nodeId} style={{ height: "100%" }}></div>
    );
}

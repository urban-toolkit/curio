import { renderHook, act } from "@testing-library/react";
import {
    useMonacoExternalValue,
    MonacoEditorLike,
} from "../../hook/useMonacoExternalValue";

// Fake Monaco editor mirroring the behavior that matters here: executeEdits
// replaces the whole content and parks the cursor at the end of the document
// (what the real editor does on a full-model-range edit).
function makeFakeEditor(initial = "") {
    let value = initial;
    let position: { lineNumber: number; column: number } = { lineNumber: 1, column: 1 };
    const model = {
        getFullModelRange: () => ({ range: "full" }),
        validatePosition: jest.fn((p: any) => ({ ...p, clamped: true })),
    };
    const editor = {
        getModel: () => model,
        getValue: () => value,
        setValue: jest.fn((v: string) => { value = v; }),
        getPosition: () => position,
        setPosition: jest.fn((p: any) => { position = p; }),
        executeEdits: jest.fn((_src: string, edits: Array<{ text: string }>) => {
            value = edits[0].text;
            position = { lineNumber: 9999, column: 9999 };
            return true;
        }),
        pushUndoStop: jest.fn(),
        // Test helpers (not part of MonacoEditorLike)
        __type: (v: string, pos = { lineNumber: 2, column: 5 }) => { value = v; position = pos; },
        __position: () => position,
        __model: model,
    };
    return editor as MonacoEditorLike & typeof editor;
}

function renderExternalValue(
    initialExternal: string | undefined,
    opts: { initialContent?: string } = {},
) {
    const onExternalApply = jest.fn();
    const rendered = renderHook(
        ({ externalValue }: { externalValue: string | undefined }) =>
            useMonacoExternalValue({
                externalValue,
                initialContent: opts.initialContent,
                onExternalApply,
            }),
        { initialProps: { externalValue: initialExternal } },
    );
    return { ...rendered, onExternalApply };
}

describe("useMonacoExternalValue", () => {
    test("ignores an undefined external value", () => {
        const editor = makeFakeEditor();
        const { result, onExternalApply } = renderExternalValue(undefined);
        act(() => result.current.attachEditor(editor));

        expect(editor.executeEdits).not.toHaveBeenCalled();
        expect(onExternalApply).not.toHaveBeenCalled();
        expect(result.current.baselineRef.current).toBe("");
    });

    test("applies a new external string to the editor, baseline, and callback", () => {
        const editor = makeFakeEditor();
        const { result, rerender, onExternalApply } = renderExternalValue(undefined);
        act(() => result.current.attachEditor(editor));

        rerender({ externalValue: "print(1)" });

        expect(editor.getValue()).toBe("print(1)");
        expect(result.current.baselineRef.current).toBe("print(1)");
        expect(onExternalApply).toHaveBeenCalledTimes(1);
        expect(onExternalApply).toHaveBeenCalledWith("print(1)");
    });

    test("ignores a value equal to the initial content (empty-model no-op)", () => {
        const editor = makeFakeEditor("{}");
        const { result, onExternalApply } = renderExternalValue("{}", { initialContent: "{}" });
        act(() => result.current.attachEditor(editor));

        expect(editor.executeEdits).not.toHaveBeenCalled();
        expect(onExternalApply).not.toHaveBeenCalled();
    });

    test("dev/70 regression: a string→undefined→same-string flip never clobbers user edits", () => {
        const editor = makeFakeEditor();
        const { result, rerender, onExternalApply } = renderExternalValue("DEFAULT_SPEC");
        act(() => result.current.attachEditor(editor));
        expect(editor.getValue()).toBe("DEFAULT_SPEC");

        // The user edits; Monaco owns the content now.
        editor.__type("USER_EDITED");

        // The oscillation that used to reset the Autark editor.
        rerender({ externalValue: undefined });
        rerender({ externalValue: "DEFAULT_SPEC" });

        expect(editor.getValue()).toBe("USER_EDITED");
        expect(onExternalApply).toHaveBeenCalledTimes(1); // the initial load only
    });

    test("restores the cursor (clamped) after an external replace", () => {
        const editor = makeFakeEditor();
        const { result, rerender } = renderExternalValue("first");
        act(() => result.current.attachEditor(editor));

        editor.__type("first", { lineNumber: 3, column: 7 });
        rerender({ externalValue: "second version" });

        // executeEdits parked the cursor at the end; the hook restores the
        // previous position through model.validatePosition.
        expect(editor.__model.validatePosition).toHaveBeenCalledWith({ lineNumber: 3, column: 7 });
        expect(editor.__position()).toEqual({ lineNumber: 3, column: 7, clamped: true });
    });

    test("keeps undo intact: apply goes through executeEdits between undo stops, not setValue", () => {
        const editor = makeFakeEditor();
        const { result, rerender } = renderExternalValue(undefined);
        act(() => result.current.attachEditor(editor));

        rerender({ externalValue: "content" });

        expect(editor.setValue).not.toHaveBeenCalled();
        expect(editor.executeEdits).toHaveBeenCalledTimes(1);
        expect(editor.pushUndoStop).toHaveBeenCalledTimes(2);
    });

    test("a value applied before mount is synced onto the editor at attach", () => {
        const { result, onExternalApply } = renderExternalValue("early content");
        // No editor yet: baseline + callback move, nothing crashes.
        expect(result.current.baselineRef.current).toBe("early content");
        expect(onExternalApply).toHaveBeenCalledWith("early content");

        const editor = makeFakeEditor();
        act(() => result.current.attachEditor(editor));
        expect(editor.getValue()).toBe("early content");
    });

    test("applyValue (collab channel) updates editor and baseline without the external callback", () => {
        const editor = makeFakeEditor();
        const { result, onExternalApply } = renderExternalValue(undefined);
        act(() => result.current.attachEditor(editor));

        act(() => result.current.applyValue("from a peer"));

        expect(editor.getValue()).toBe("from a peer");
        expect(result.current.baselineRef.current).toBe("from a peer");
        expect(onExternalApply).not.toHaveBeenCalled();
    });

    test("an external value equal to the current baseline re-sent later stays a no-op", () => {
        const editor = makeFakeEditor();
        const { result, rerender, onExternalApply } = renderExternalValue("v1");
        act(() => result.current.attachEditor(editor));
        expect(onExternalApply).toHaveBeenCalledTimes(1);

        rerender({ externalValue: "v2" });
        expect(onExternalApply).toHaveBeenCalledTimes(2);
        expect(editor.getValue()).toBe("v2");

        editor.__type("v2 plus typing");
        rerender({ externalValue: "v2" }); // stale re-send of the applied value
        expect(editor.getValue()).toBe("v2 plus typing");
        expect(onExternalApply).toHaveBeenCalledTimes(2);
    });
});

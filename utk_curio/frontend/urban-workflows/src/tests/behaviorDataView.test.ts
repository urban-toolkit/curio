/**
 * dev/90 A15 — behaviorDataView regression coverage.
 *
 * The live curio.notes@1 bundle read `data.content` while the runtime
 * delivers the note text as `data.code`: the applied node rendered its
 * "No content provided" placeholder despite a correct spec. The view
 * aliases code → content per render, never mutating or persisting.
 */
import { behaviorDataView } from "../utils/behaviorDataView";

describe("behaviorDataView (dev/90 A15)", () => {
    it("aliases data.code onto data.content when content is absent", () => {
        const data = { nodeType: "curio.notes/note-surface@1", code: "### Weather in Paris" };
        const view = behaviorDataView(data);
        expect(view.content).toBe("### Weather in Paris");
        expect(view.code).toBe("### Weather in Paris");
    });

    it("never overwrites an explicit content field", () => {
        const data = { code: "canonical", content: "explicit" };
        expect(behaviorDataView(data).content).toBe("explicit");
    });

    it("returns the SAME object when no alias is needed (stable identity)", () => {
        const data = { code: "x", content: "y" };
        expect(behaviorDataView(data)).toBe(data);
    });

    it("never mutates the underlying node data (TrillGenerator still sees code only)", () => {
        const data: { code: string; content?: string } = { code: "x" };
        const view = behaviorDataView(data);
        expect(view).not.toBe(data);
        expect(data.content).toBeUndefined();
    });

    it("is a view: a behavior's own writes reach the node data, and content is never written", () => {
        const data: { code: string; content?: string; widgets?: unknown[] } = { code: "x" };
        const view = behaviorDataView(data) as typeof data;
        const widgets = [{ name: "season", type: "text", default: "winter" }];
        view.widgets = widgets;
        expect(data.widgets).toBe(widgets);
        view.content = "other";
        expect(data.content).toBeUndefined();
        expect(view.content).toBe("x");
        expect("content" in view).toBe(true);
        // A spread (updateDataNode(id, { ...data, ... })) carries no alias.
        expect({ ...view }).toEqual({ code: "x", widgets });
    });

    it("passes null-ish and content-less data through without throwing", () => {
        expect(behaviorDataView(null as any)).toBeNull();
        const empty = behaviorDataView({} as any);
        expect(empty.content).toBeUndefined();
    });
});

/**
 * Is the de-overlap pass wired into the ONE place that covers every load?
 *
 * Read as source rather than exercised, the same way
 * `loadPathsMarkDirty.test.ts` reads these files: `useCode` cannot be mounted
 * without the whole provider stack, and what is worth pinning here is placement,
 * which a behavioural test would not catch anyway.
 *
 * Placement is the whole design. The pass has to run after the node-build loop
 * and before `loadParsedTrill`, because that is the last point where positions
 * can be changed without React Flow emitting `position` changes -- which
 * `MainCanvas.handleNodesChange` treats as an edit. Move it after mount and
 * every project reads "unsaved changes" the moment it opens, which is #229
 * coming back through a different door.
 *
 * This file also guards its sibling: `loadPathsMarkDirty` slices `useCode.ts`
 * with `indexOf` on three literals, so a new branch above them that happened to
 * repeat one would silently invert that suite's assertions without failing it.
 */
import * as fs from "fs";
import * as path from "path";

function read(relative: string): string {
    return fs.readFileSync(path.join(__dirname, "..", "..", relative), "utf-8");
}

const USE_CODE = read("hook/useCode.ts");

describe("de-overlap on load", () => {
    test("loadTrill separates the nodes it just built", () => {
        expect(USE_CODE).toContain("deoverlapNodes");
        expect(USE_CODE).toMatch(
            /import \{ deoverlapNodes \} from "\.\.\/utils\/deoverlapLayout";/,
        );
    });

    test("the call sits after the node loop and before the load branches", () => {
        const call = USE_CODE.indexOf("nodes = deoverlapNodes(nodes)");
        const built = USE_CODE.indexOf("nodes.push(generateCodeNode(");
        const branches = USE_CODE.indexOf("if (fromProvenance)");

        expect(call).toBeGreaterThan(built);
        expect(call).toBeLessThan(branches);
    });

    test("it is skipped for a suggestion, which is merged into a live graph", () => {
        const call = USE_CODE.indexOf("nodes = deoverlapNodes(nodes)");
        const guard = USE_CODE.lastIndexOf("if (suggestionType === undefined)", call);

        expect(guard).toBeGreaterThan(-1);
        // Guard and call adjacent, not merely both present somewhere above.
        expect(USE_CODE.slice(guard, call)).toMatch(/^if \(suggestionType === undefined\) \{\s*$/m);
    });

    test("loading still does not mark the dataflow dirty", () => {
        // The pass runs pre-mount precisely so it does not need to. If this
        // grows a markDirty(), opening a tidy project starts reporting an edit.
        const loop = USE_CODE.indexOf("for(const node of trill.dataflow.nodes)");
        const branches = USE_CODE.indexOf("if (fromProvenance)");

        expect(USE_CODE.slice(loop, branches)).not.toContain("markDirty()");
    });

    test("it does not touch the dashboard's workflowPosition", () => {
        // That key belongs to the dashboard page's layout pass
        // (`prepareDashboardNodes`); setting it here would pin what
        // TrillGenerator persists for every later save.
        const layout = read("utils/deoverlapLayout.ts");

        expect(layout).not.toMatch(/workflowPosition\s*[:=]/);
    });

    test("the anchors loadPathsMarkDirty slices on are still unique", () => {
        // Its assertions are `indexOf` slices. A second occurrence of any of
        // these above the real one would move a slice boundary and quietly
        // invert "does NOT mark dirty on the project-open branch".
        for (const anchor of [
            "if (fromProvenance)",
            "} else if(suggestionType == undefined)",
            "const generateCodeNode",
        ]) {
            expect(USE_CODE.split(anchor)).toHaveLength(2);
        }
    });
});

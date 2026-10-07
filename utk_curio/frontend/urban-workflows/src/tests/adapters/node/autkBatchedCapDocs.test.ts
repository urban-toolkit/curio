/**
 * Does example 07's walkthrough say how many features autk-grammar packs into
 * a batched compute?
 *
 * The walkthrough says the runtime stacks every source feature's values into
 * the arrays the shader loops over, and names no cap. autk-grammar packs as
 * many features as a pass's largest array fits in one storage buffer binding:
 * eight f32 per feature for a matrix entry such as the buildings' `ring`. The
 * binding size is read from the installed package's type declarations, so a
 * grammar that packs fewer building parts than a shipped example batches fails
 * here, and so does a walkthrough that names a cap again (#757).
 */
import * as fs from "fs";
import * as path from "path";

const REPO_ROOT = path.join(__dirname, "..", "..", "..", "..", "..", "..", "..");
const WALKTHROUGH = path.join(REPO_ROOT, "docs", "examples", "07-autark-gpu-shader.md");
const GRAMMAR_TYPES = path.resolve(
    __dirname, "../../../../node_modules/@urban-toolkit/autk-grammar/dist/index.d.ts",
);

/** Bytes a feature takes in a batched matrix entry: its bounding box, eight f32. */
const BOX_BYTES = 8 * 4;
/** The most building parts a shipped example's shader batches: Back Bay's, in example 06. */
const MOST_BATCHED_PARTS = 2108;

function grammarBindingSize(): number {
    const types = fs.readFileSync(GRAMMAR_TYPES, "utf-8");
    const match = types.match(/export declare const STORAGE_BUFFER_BINDING_SIZE = (\d+);/);
    if (!match) throw new Error("autk-grammar's index.d.ts declares no STORAGE_BUFFER_BINDING_SIZE");
    return Number(match[1]);
}

test("example 07 says a batched compute packs every source feature, and names no cap", () => {
    const doc = fs.readFileSync(WALKTHROUGH, "utf-8");
    expect(doc).toContain("the runtime stacks every source feature's values");
    expect(doc).not.toMatch(/\bcap(s|ped)?\b/i);
});

test("autk-grammar packs every building part a shipped example batches", () => {
    expect(Math.floor(grammarBindingSize() / BOX_BYTES)).toBeGreaterThanOrEqual(MOST_BATCHED_PARTS);
});

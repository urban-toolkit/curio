/**
 * Does example 07's walkthrough state the batched feature cap the grammar
 * enforces?
 *
 * autk-grammar's `MAX_BATCHED_FEATURES` decides how many source features a
 * `batched` directive packs. The cap is read from the installed package's type
 * declarations, so a grammar upgrade that moves it fails here until the
 * walkthrough says the new number.
 */
import * as fs from "fs";
import * as path from "path";

const REPO_ROOT = path.join(__dirname, "..", "..", "..", "..", "..", "..", "..");
const WALKTHROUGH = path.join(REPO_ROOT, "docs", "examples", "07-autark-gpu-shader.md");

function grammarCap(): number {
    const dist = path.dirname(require.resolve("@urban-toolkit/autk-grammar"));
    const types = fs.readFileSync(path.join(dist, "index.d.ts"), "utf-8");
    const match = types.match(/export declare const MAX_BATCHED_FEATURES = (\d+);/);
    if (!match) throw new Error("autk-grammar's index.d.ts declares no MAX_BATCHED_FEATURES");
    return Number(match[1]);
}

test("example 07 states autk-grammar's batched feature cap", () => {
    const doc = fs.readFileSync(WALKTHROUGH, "utf-8");
    const stated = [...doc.matchAll(/caps the source feature count at \*\*(\d+)\*\*/g)]
        .map((m) => Number(m[1]));
    expect(stated).toHaveLength(1);
    expect(stated[0]).toBe(grammarCap());
});

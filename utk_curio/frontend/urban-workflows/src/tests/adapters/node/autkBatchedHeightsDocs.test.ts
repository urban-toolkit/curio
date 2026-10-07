/**
 * Does example 07 say what happens to a building part with no `height` tag?
 *
 * Its shadow step reads every building's `properties.height` with
 * `required: true`, so autk-grammar would leave out a building whose height
 * is not a number. Curio first gives every building part the height autk-map
 * draws for it (`readableBuildingProperties`), so the shader reads every part.
 * The walkthrough says so, and the step's goal, which an agent reads when
 * example 07 is a worked example, says the same: no text of the dataflow says
 * a building is skipped, and the goal and the walkthrough both give the
 * heights the code gives (#757).
 */
import * as fs from "fs";
import * as path from "path";

import { METRES_PER_LEVEL, deriveBuildingHeight } from "../../../utils/buildingHeight";

const REPO_ROOT = path.join(__dirname, "..", "..", "..", "..", "..", "..", "..");
const EXAMPLE = path.join(REPO_ROOT, "docs", "examples", "07-autark-gpu-shader");

/** Words that say a building is not counted. */
const LEFT_OUT = /\b(skip(s|ped)?|drop(s|ped)?|omit(s|ted)?|exclude[sd]?|left out|leaves? out)\b/i;

/** The heights Curio gives a building part with no `height` tag, as both texts state them. */
const HEIGHT_RULE = [`${METRES_PER_LEVEL} m each`, `${deriveBuildingHeight({})} m above its base`];

function dataflow(): any {
    return JSON.parse(fs.readFileSync(`${EXAMPLE}.json`, "utf-8")).dataflow;
}

function spec(node: any): any {
    try {
        return JSON.parse(node.content || "{}");
    } catch {
        return {};
    }
}

/** The node whose batched compute reads every building's height with `required: true`. */
function shadowStep(): any {
    const steps = dataflow().nodes.filter((node: any) =>
        (spec(node).compute ?? []).some((pass: any) =>
            Object.values(pass?.uniforms ?? {}).some((uniform: any) =>
                uniform?.fromFeature?.iterate === "batched"
                && uniform.fromFeature.path === "properties.height"
                && uniform.fromFeature.required === true)));
    expect(steps).toHaveLength(1);
    return steps[0];
}

test("no text of example 07's dataflow says a building is skipped", () => {
    const flow = dataflow();
    const texts = [flow.name, flow.task, flow.description, ...flow.nodes.map((node: any) => node.goal)]
        .filter((text: unknown): text is string => typeof text === "string" && text !== "");
    expect(texts.filter((text) => LEFT_OUT.test(text))).toEqual([]);
});

test("example 07's shadow step and its walkthrough give every building part the height Curio gives it", () => {
    const goal: string = shadowStep().goal ?? "";
    const doc = fs.readFileSync(`${EXAMPLE}.md`, "utf-8").replace(/\s+/g, " ");
    expect(doc).toContain("Curio gives every building part a height");
    expect(doc).toContain("so none is dropped here");
    expect(goal.toLowerCase()).toContain("every building part");
    for (const words of HEIGHT_RULE) {
        expect(doc).toContain(words);
        expect(goal).toContain(words);
    }
});

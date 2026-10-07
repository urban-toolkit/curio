/**
 * Do the shipped texts about a shadow step say what happens to a building part
 * with no `height` tag?
 *
 * The shadow steps of examples 06 and 07 read every building's
 * `properties.height` with `required: true`, so autk-grammar would leave out a
 * building whose height is not a number. Curio first gives every building part
 * the height autk-map draws for it (`readableBuildingProperties`), so the
 * shader reads every part and no Autark compute meets a building with no
 * height. The texts say the same:
 * - no text of either dataflow says a building is skipped;
 * - each shadow step's goal, which an agent reads when the example is a worked
 *   example, gives the heights the code gives, and so does example 07's
 *   walkthrough;
 * - a text that gives a building its OpenStreetMap height (a scenario's
 *   description, a walkthrough) also gives what a part without one gets;
 * - no line of the worked-examples index says a compute fills a missing
 *   height (#757).
 */
import * as fs from "fs";
import * as path from "path";

import { METRES_PER_LEVEL, deriveBuildingHeight } from "../../../utils/buildingHeight";
import { REFERENCE_PATTERN } from "../../../utils/references/codeReferences";

const REPO_ROOT = path.join(__dirname, "..", "..", "..", "..", "..", "..", "..");
const EXAMPLES = path.join(REPO_ROOT, "docs", "examples");
const WORKED_EXAMPLES_INDEX = path.join(REPO_ROOT, "utk_curio", "llm-prompts", "examples.md");

/** The examples with shadow steps, and how many each has. */
const SHADOW_EXAMPLES: [string, string, number][] = [
    ["example 06", "06-autark-what-if-shadow-study", 3],
    ["example 07", "07-autark-gpu-shader", 1],
];

/** Words that say a building is not counted. */
const LEFT_OUT = /\b(skip(s|ped)?|drop(s|ped)?|omit(s|ted)?|exclude[sd]?|left out|leaves? out)\b/i;

/** Words that give a building its OpenStreetMap height. */
const OSM_HEIGHT = /\b(OSM|OpenStreetMap)\W+height/i;

/** Words that say a building reaches a compute with no height. */
const MISSING_HEIGHT = /\bmissing heights?\b|\bheights? (are |is )?(filled|skipped|dropped)\b/i;

/** The heights Curio gives a building part with no `height` tag, as the texts state them. */
const HEIGHT_RULE = [`${METRES_PER_LEVEL} m each`, `${deriveBuildingHeight({})} m above its base`];

function dataflow(stem: string): any {
    return JSON.parse(fs.readFileSync(path.join(EXAMPLES, `${stem}.json`), "utf-8")).dataflow;
}

function walkthrough(stem: string): string {
    return fs.readFileSync(path.join(EXAMPLES, `${stem}.md`), "utf-8").replace(/\s+/g, " ");
}

/** A node's spec, its `[!! ... !!]` references read as null. */
function spec(node: any): any {
    try {
        return JSON.parse(String(node.content || "{}").replace(new RegExp(REFERENCE_PATTERN, "g"), "null"));
    } catch {
        return {};
    }
}

/** The nodes whose batched compute reads every building's height with `required: true`. */
function shadowSteps(stem: string): any[] {
    return dataflow(stem).nodes.filter((node: any) =>
        (spec(node).compute ?? []).some((pass: any) =>
            Object.values(pass?.uniforms ?? {}).some((uniform: any) =>
                uniform?.fromFeature?.iterate === "batched"
                && uniform.fromFeature.path === "properties.height"
                && uniform.fromFeature.required === true)));
}

/** What the dataflow says in words: its name, task and description, its nodes' goals, its scenarios' names and descriptions. */
function texts(stem: string): string[] {
    const flow = dataflow(stem);
    return [
        flow.name, flow.task, flow.description,
        ...flow.nodes.map((node: any) => node.goal),
        ...(flow.scenarios ?? []).flatMap((scenario: any) => [scenario.name, scenario.description]),
    ].filter((text: unknown): text is string => typeof text === "string" && text !== "");
}

test.each(SHADOW_EXAMPLES)("no text of %s's dataflow says a building is skipped", (_label, stem) => {
    expect(texts(stem).filter((text) => LEFT_OUT.test(text))).toEqual([]);
});

test("example 07's shadow step and its walkthrough give every building part the height Curio gives it", () => {
    const steps = shadowSteps("07-autark-gpu-shader");
    expect(steps).toHaveLength(1);
    const goal: string = steps[0].goal ?? "";
    const doc = walkthrough("07-autark-gpu-shader");
    expect(doc).toContain("Curio gives every building part a height");
    expect(doc).toContain("so none is dropped here");
    expect(goal.toLowerCase()).toContain("every building part");
    for (const words of HEIGHT_RULE) {
        expect(doc).toContain(words);
        expect(goal).toContain(words);
    }
});

test.each(SHADOW_EXAMPLES)("every shadow step of %s gives every building part the height Curio gives it", (_label, stem, count) => {
    const steps = shadowSteps(stem);
    expect(steps).toHaveLength(count);
    for (const step of steps) {
        const goal: string = step.goal ?? "";
        expect(goal.toLowerCase()).toContain("every building part");
        for (const words of HEIGHT_RULE) expect(goal).toContain(words);
    }
});

test.each(SHADOW_EXAMPLES)("a text of %s that gives a building its OpenStreetMap height gives what a part without one gets", (_label, stem) => {
    const said = [...texts(stem), walkthrough(stem)].filter((text) => OSM_HEIGHT.test(text));
    for (const text of said) {
        for (const words of HEIGHT_RULE) expect(text).toContain(words);
    }
});

test("no line of the worked-examples index says a compute meets a building with no height", () => {
    const lines = fs.readFileSync(WORKED_EXAMPLES_INDEX, "utf-8").split("\n");
    expect(lines.filter((line) => MISSING_HEIGHT.test(line))).toEqual([]);
});

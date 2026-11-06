/**
 * A filtered Full stack build starts only the jobs and parts that hold a
 * selected test; every other run starts every one of them.
 *
 * A run is filtered when it is a re-mint with a remint_filter, or when its
 * tests input is set. build-image then lists each suite's selected tests
 * (CURIO_LIST_PARTS, utk_curio/backend/tests/parts.py) into its holding
 * output, and each e2e-desktop part and unit entry that holds none skips its
 * steps; test-gpu lists its own share before it starts a stack. A push, a PR,
 * the schedule and the Weekly flake hunt's repeat-10 dispatch must run as
 * before: nothing filters unless one of the two inputs is set, and an empty
 * holding output runs every part. The workflow is read as text, step by step,
 * as ciParts.test.ts reads it.
 */
import { read } from "./_support/workflowPaths";

const WORKFLOW = ".github/workflows/docker-compose.yml";
const SCRIPT = "scripts/ci_selected_tests.py";
const FILTER = "(inputs.remint && inputs.remint_filter) || inputs.tests";

/** One job of the workflow: its lines from `  <job>:` to the next job. */
function jobBlock(job: string): string {
    const lines = read(WORKFLOW).split("\n");
    const start = lines.findIndex((line) => line === `  ${job}:`);
    if (start < 0) throw new Error(`${WORKFLOW} has no job ${job}`);
    const end = lines.findIndex((line, i) => i > start && /^ {2}[A-Za-z0-9_-]+:\s*$/.test(line));
    return lines.slice(start, end < 0 ? undefined : end).join("\n");
}

/** Every job of the workflow, in its order. */
function jobNames(): string[] {
    const lines = read(WORKFLOW).split("\n");
    const start = lines.indexOf("jobs:");
    return lines.slice(start + 1).flatMap((line) => /^ {2}([A-Za-z0-9_-]+):\s*$/.exec(line)?.slice(1, 2) ?? []);
}

interface Step {
    text: string;
    id: string;
    condition: string;
}

/**
 * A job's steps, in their order, each with its id and its `if:` (one line, or
 * a `>-` block). A comment above a step ends the step before it, so a step's
 * text leaves its comment lines out.
 */
function steps(job: string): Step[] {
    return jobBlock(job)
        .split(/\n(?= {6}- )/)
        .slice(1)
        .map((chunk) => {
            const lines = chunk.split("\n").filter((line) => !/^\s*#/.test(line));
            const text = lines.join("\n");
            const at = lines.findIndex((line) => /^ {6}- if:|^ {8}if:/.test(line));
            let condition = "";
            if (at >= 0) {
                condition = lines[at].replace(/^ {6}- if:|^ {8}if:/, "").trim();
                if (condition === ">-") {
                    condition = lines
                        .slice(at + 1)
                        .filter((line, i, rest) => rest.slice(0, i + 1).every((l) => /^ {10}/.test(l)))
                        .map((line) => line.trim())
                        .join(" ");
                }
            }
            return { text, id: /^ {8}id: (\S+)$/m.exec(text)?.[1] ?? "", condition };
        });
}

/** Whether a step runs only under `holds`, itself or through the step whose outcome its `if:` reads. */
function gatedBy(all: Step[], step: Step, holds: (condition: string) => boolean): boolean {
    if (holds(step.condition)) return true;
    const reads = [...step.condition.matchAll(/steps\.([A-Za-z0-9_-]+)\./g)].map((match) => match[1]);
    return reads.some((id) => {
        const earlier = all.find((other) => other.id === id);
        return earlier !== undefined && earlier !== step && gatedBy(all, earlier, holds);
    });
}

/** The `if:` of a job itself (its own key, one line or a `>-` block). */
function jobCondition(job: string): string {
    const lines = jobBlock(job).split("\n");
    const at = lines.findIndex((line) => /^ {4}if:/.test(line));
    if (at < 0) return "";
    const first = lines[at].replace(/^ {4}if:/, "").trim();
    if (first !== ">-") return first;
    const rest = lines.slice(at + 1);
    const end = rest.findIndex((line) => !/^ {6}/.test(line));
    return rest
        .slice(0, end < 0 ? undefined : end)
        .map((line) => line.trim())
        .join(" ");
}

/** A string constant of the selection script, such as its suites' folders; `{NAME}` reads another. */
function scriptConstant(name: string): string {
    const match = new RegExp(`^${name} = f?"([^"]*)"$`, "m").exec(read(SCRIPT));
    if (!match) throw new Error(`${SCRIPT} has no line ${name} = "..."`);
    return match[1].replace(/\{([A-Z0-9_]+)\}/g, (_, other: string) => scriptConstant(other));
}

describe("a filtered Full stack build", () => {
    test("the Weekly flake hunt dispatches the whole suite, with no filter", () => {
        const dispatches = read(".github/workflows/weekly-flake-hunt.yml")
            .split("\n")
            .filter((line) => line.includes("gh workflow run docker-compose.yml"));
        expect(dispatches).toHaveLength(1);
        expect(dispatches[0]).toContain("-f repeat=10");
        expect(dispatches[0]).not.toMatch(/remint|tests/);
    });

    test("tests is a dispatch input, empty unless a dispatch sets it", () => {
        expect(read(WORKFLOW)).toMatch(/^ {6}tests:\n {8}description: '[^'\n]+'\n {8}type: string\n {8}default: ''$/m);
    });

    test("a condition reads the two inputs only as the filter, or to skip a job that a tests run does not need", () => {
        // What is left of each condition once the filter and the skips are taken out names neither input.
        const skips = [
            /\(!inputs\.tests \|\|(?:\s*contains\(inputs\.tests, '[^']+'\)\s*(?:\|\||\)))+/g,
            /!inputs\.tests\b/g,
        ];
        const conditions: [string, string][] = jobNames().flatMap((job): [string, string][] => [
            [job, jobCondition(job)],
            ...steps(job).map((step): [string, string] => [job, step.condition]),
        ]);
        const left = conditions
            .map(([job, condition]): [string, string] => [
                job,
                skips.reduce((rest, skip) => rest.replace(skip, ""), condition.split(FILTER).join("")),
            ])
            .filter(([, rest]) => /inputs\.(tests|remint_filter)\b/.test(rest));
        expect(left).toEqual([]);
        // The filter is there, in the steps that collect and in ci-report's check.
        expect(conditions.filter(([, condition]) => condition.includes(FILTER)).length).toBeGreaterThanOrEqual(6);
    });

    test("only a filter collects, lists or checks the selected tests", () => {
        const machinery = /CURIO_LIST_PARTS|ci_selected_tests\.py (split|check|holding)|name: ci-selected/;
        const unfiltered: string[] = [];
        for (const job of jobNames()) {
            const all = steps(job);
            for (const step of all) {
                if (machinery.test(step.text) && !gatedBy(all, step, (condition) => condition.includes(FILTER))) {
                    unfiltered.push(`${job}: ${/name: (.*)/.exec(step.text)?.[1] ?? step.text.slice(0, 60)}`);
                }
            }
        }
        expect(unfiltered).toEqual([]);
        // build-image's holding output comes from its collection, which only a filter starts, or
        // from the step after it that names the selected suites' parts when it failed.
        expect(jobBlock("build-image")).toMatch(
            /^ {6}holding: \$\{\{ steps\.select\.outputs\.holding \|\| steps\.unlisted\.outputs\.holding \}\}$/m,
        );
        const unlisted = steps("build-image").find((step) => step.id === "unlisted");
        expect(unlisted?.condition).toBe("steps.select.outcome == 'failure'");
        expect(unlisted?.text).toContain("ci_selected_tests.py holding --whole-suites");
    });

    test.each([
        ["e2e-desktop", "format(',e2e-desktop-{0},', matrix.part)"],
        ["unit", "format(',unit-{0},', matrix.name)"],
    ])("%s runs every part when build-image's holding is empty, and starts nothing after its checkout in one that holds none", (job, key) => {
        const block = jobBlock(job);
        expect(block).toContain(
            `      CURIO_CI_HOLDS: \${{ needs.build-image.outputs.holding == '' || contains(needs.build-image.outputs.holding, ${key}) }}`,
        );
        const all = steps(job);
        const checkout = all.findIndex((step) => step.text.includes("uses: actions/checkout@"));
        expect(checkout).toBeGreaterThanOrEqual(0);
        const ungated = all
            .slice(checkout + 1)
            .filter((step) => !gatedBy(all, step, (condition) => condition.includes("env.CURIO_CI_HOLDS == 'true'")))
            .map((step) => /name: (.*)/.exec(step.text)?.[1] ?? step.text.trim().split("\n")[0]);
        expect(ungated).toEqual([]);
    });

    test("test-gpu lists its own share before its stack, and with none stops there but for its teardown", () => {
        const all = steps("test-gpu");
        const asks = all.findIndex((step) => step.text.includes("--job test-gpu"));
        const starts = all.findIndex((step) => step.text.includes("docker compose -p curio-ci up -d"));
        expect(asks).toBeGreaterThanOrEqual(0);
        expect(starts).toBeGreaterThan(asks);
        expect(all[asks].condition).toBe(`\${{ ${FILTER} }}`);
        expect(all[asks].text).toContain('"$GITHUB_ENV"');
        const ungated = all
            .slice(asks + 1)
            .filter((step) => !step.text.includes("uses: ./.github/actions/stop-stack"))
            .filter((step) => !gatedBy(all, step, (condition) => condition.includes("env.CURIO_CI_HOLDS")))
            .map((step) => /name: (.*)/.exec(step.text)?.[1] ?? step.text.trim().split("\n")[0]);
        expect(ungated).toEqual([]);
        // A run without a filter never sets CURIO_CI_HOLDS, so every step runs: each asks it is not 'false'.
        const asking = all.slice(asks + 1).map((step) => step.condition).filter((c) => c.includes("env.CURIO_CI_HOLDS"));
        expect(asking.filter((c) => !/env\.CURIO_CI_HOLDS (!= 'false'|== '')/.test(c))).toEqual([]);
    });

    test("ci-report puts a lone job's results in their folder before anything reads them", () => {
        // download-artifact extracts a lone pattern match into its path itself, as when a
        // filtered run's one part sent results; every check reads inputs/ci-inputs-<job>/.
        const all = steps("ci-report");
        const download = all.findIndex((step) => /pattern: ci-inputs-\*/.test(step.text));
        expect(download).toBeGreaterThanOrEqual(0);
        const next = all[download + 1];
        expect(next.condition).toBe("");
        expect(next.text).toContain('mv "${files[@]}" "inputs/$name/"');
    });

    test("the folders a job's condition looks for are the selection script's suites", () => {
        const folders = [scriptConstant("E2E"), scriptConstant("BACKEND"), scriptConstant("SANDBOX"), `${scriptConstant("JEST")}/`];
        const named = [...read(WORKFLOW).matchAll(/contains\(inputs\.tests, '([^']+)'\)/g)].map((match) => match[1]);
        expect(named.length).toBeGreaterThan(0);
        expect(named.filter((folder) => !folders.includes(folder))).toEqual([]);
    });
});

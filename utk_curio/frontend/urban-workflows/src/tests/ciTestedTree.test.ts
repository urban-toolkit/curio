/**
 * Main's run of a tree a run already tested green passes by a link to it.
 *
 * In .github/workflows/docker-compose.yml, ci-report names an artifact after
 * the tree a green run tested, and pick-runners, on a push to main, looks one
 * up (scripts/ci_tested_tree.py) and sets `tested_by`, which every test job
 * skips on. Each piece read wrong would leave a tree untested: a lookup on a
 * dispatch would skip the Weekly flake hunt's repeat-10 run, a job without the
 * condition would run anyway, and a name given by a red or partial run would
 * vouch for a tree nobody tested whole.
 */
import { read } from "./_support/workflowPaths";

const WORKFLOW = ".github/workflows/docker-compose.yml";

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

/** An `if:` at `indent` spaces in `block`, folded lines joined: one line, or `>-` and the deeper lines under it. */
function condition(block: string, indent: number): string {
    const lines = block.split("\n");
    const start = lines.findIndex((line) => line.startsWith(`${" ".repeat(indent)}if:`));
    if (start < 0) return "";
    const first = lines[start].slice(indent + 3).trim();
    if (first !== ">-") return first;
    const rest = [];
    for (const line of lines.slice(start + 1)) {
        if (line.length - line.trimStart().length <= indent) break;
        rest.push(line.trim());
    }
    return rest.join(" ");
}

/** One step of a job, from its `- name:` line to the next step. */
function step(job: string, name: string): string {
    const lines = jobBlock(job).split("\n");
    const start = lines.findIndex((line) => /^ {6}- name: /.test(line) && line.includes(name));
    if (start < 0) throw new Error(`${job} has no step named ${name}`);
    const end = lines.findIndex((line, i) => i > start && /^ {6}- /.test(line));
    return lines.slice(start, end < 0 ? undefined : end).join("\n");
}

const GATE = "needs.pick-runners.outputs.tested_by == ''";

describe("main's run of a tree a run already tested green", () => {
    test("only a push to main looks for one, so dispatches and the schedule always test", () => {
        expect(condition(step("pick-runners", "Look for a green run"), 8)).toBe(
            "github.event_name == 'push' && github.ref == 'refs/heads/main'",
        );
        expect(jobKeyLine("pick-runners", "tested_by")).toBe("${{ steps.tested.outputs.run }}");
    });

    test("every job that tests skips when pick-runners names such a run", () => {
        // pick-runners finds it; build-image still runs, so that main's layer
        // cache gets new early layers; test-gpu-stress never runs on a push.
        const notTesting = ["pick-runners", "build-image", "test-gpu-stress"];
        const ungated = jobNames()
            .filter((job) => !notTesting.includes(job))
            .filter((job) => !condition(jobBlock(job), 4).includes(GATE));
        expect(ungated).toEqual([]);
        expect(condition(jobBlock("test-gpu-stress"), 4)).not.toContain("'push'");
    });

    test("only a run with every job green and nothing re-minted names its tree", () => {
        const named = condition(step("ci-report", "Name the tree this run tested green"), 8);
        for (const part of [
            "success()",
            "!inputs.remint",
            "!contains(needs.*.result, 'failure')",
            "!contains(needs.*.result, 'cancelled')",
            "!contains(needs.*.result, 'skipped')",
        ]) {
            expect(named).toContain(part);
        }
        // After the check that every test ran, whose failure turns success() off.
        const block = jobBlock("ci-report");
        expect(block.indexOf("Name the tree this run tested green")).toBeGreaterThan(
            block.indexOf("Fail on a test that no job ran"),
        );
    });

    test("ci-report waits for every job that tests, so needs.*.result covers them all", () => {
        const needs = /^ {4}needs:\s*\[(.*)\]\s*$/m.exec(jobBlock("ci-report"))?.[1].split(/,\s*/) ?? [];
        const testing = jobNames().filter((job) => !["pick-runners", "build-image", "test-gpu-stress", "ci-report"].includes(job));
        expect(testing.filter((job) => !needs.includes(job))).toEqual([]);
    });
});

/** The value of `  <key>:` under a job's `outputs:`. */
function jobKeyLine(job: string, key: string): string {
    return new RegExp(`^ {6}${key}:\\s*(.*)$`, "m").exec(jobBlock(job))?.[1] ?? "";
}

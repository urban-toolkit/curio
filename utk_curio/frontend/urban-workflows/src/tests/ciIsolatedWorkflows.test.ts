/**
 * The isolated stack's e2e (test-isolated) runs the dataflows its job's
 * ISOLATED_WORKFLOWS names, on a CPU runner whose browser has no WebGPU.
 * Examples 31 and 33 map their walk on an Autark map, which puts them on the
 * GPU runner (test_e2e_runner_split.py), so they are not among them. Only the workflow
 * holds the list, and the unit suites' container has no .github, so it is
 * checked here.
 */
import { read } from "./_support/workflowPaths";

const WORKFLOW = ".github/workflows/docker-compose.yml";

/** The dataflows of the workflow's one ISOLATED_WORKFLOWS line. */
function isolatedWorkflows(): string[] {
    const lists = read(WORKFLOW)
        .split("\n")
        .flatMap((line) => {
            const found = /^\s*ISOLATED_WORKFLOWS: (\S+)\s*$/.exec(line);
            return found ? [found[1]] : [];
        });
    expect(lists).toHaveLength(1);
    return lists[0].split(",");
}

describe("the isolated stack's dataflows", () => {
    test("examples 31 and 33 are not among them", () => {
        expect(isolatedWorkflows()).not.toContain("31-sideseeing-objects-along-a-walk.json");
        expect(isolatedWorkflows()).not.toContain("33-sideseeing-frames-segments-blocks.json");
    });
});

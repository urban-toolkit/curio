/**
 * The isolated stack's e2e (test-isolated) runs the dataflows its job's
 * ISOLATED_WORKFLOWS names, on a CPU runner whose browser has no WebGPU.
 * Example 31 maps its walk on an Autark map, which puts it on the GPU runner
 * (test_e2e_runner_split.py), so it is not one of them. Only the workflow
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
    test("example 31 is not one of them", () => {
        expect(isolatedWorkflows()).not.toContain("31-sideseeing-objects-along-a-walk.json");
    });
});

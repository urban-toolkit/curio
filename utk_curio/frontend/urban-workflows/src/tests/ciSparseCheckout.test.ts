/**
 * A sparse checkout on a self-hosted runner outlives its job.
 *
 * actions/checkout's `sparse-checkout-cone-mode: false` sets core.sparseCheckout
 * in the workspace's own .git/config. A later checkout with no sparse list runs
 * `git sparse-checkout disable`, which writes the off switch to config.worktree,
 * then unsets extensions.worktreeConfig, so git reads the .git/config switch
 * again and the checkout cuts the tree back to the old list. On 11-07 the
 * Weekly flake hunt's report job did this on arcade-cpu-05, and every job there
 * after it found no .github/actions/start-stack. A self-hosted runner keeps its
 * workspace, so no job that can take one checks out sparse, and each forgets a
 * sparse checkout an earlier job left before its own checkout.
 */
import * as fs from "fs";
import * as path from "path";
import { read, REPO_ROOT } from "./_support/workflowPaths";

const WORKFLOWS = ".github/workflows";
const FORGET = ["git config --local --unset-all core.sparseCheckout", "rm -f .git/info/sparse-checkout"];

interface Job {
    workflow: string;
    name: string;
    block: string;
}

/** Every job of every workflow: its lines from `  <job>:` to the next job. */
function jobs(): Job[] {
    return fs
        .readdirSync(path.join(REPO_ROOT, WORKFLOWS))
        .filter((file) => /\.ya?ml$/.test(file))
        .sort()
        .flatMap((file) => {
            const workflow = `${WORKFLOWS}/${file}`;
            const lines = read(workflow).split("\n");
            const start = lines.indexOf("jobs:");
            if (start < 0) return [];
            const heads = lines.flatMap((line, i) => (i > start && /^ {2}[A-Za-z0-9_-]+:\s*$/.test(line) ? [i] : []));
            return heads.map((head, k) => ({
                workflow,
                name: lines[head].trim().slice(0, -1),
                block: lines.slice(head, heads[k + 1]).join("\n"),
            }));
        });
}

/** Only a job whose runs-on is one GitHub-hosted image gets a fresh workspace every time. */
function canTakeSelfHosted(job: Job): boolean {
    const runsOn = /^ {4}runs-on:\s*(.+)$/m.exec(job.block)?.[1].trim() ?? "";
    return !/^(ubuntu|windows|macos)-[A-Za-z0-9.-]+$/.test(runsOn);
}

/** The step `- &<name>` starts in a workflow, which `- *<name>` repeats. */
function anchored(workflow: string, name: string): string {
    const lines = read(workflow).split("\n");
    const start = lines.findIndex((line) => line.trim() === `- &${name}`);
    if (start < 0) throw new Error(`${workflow} has no &${name}`);
    const indent = " ".repeat(lines[start].indexOf("-"));
    const end = lines.findIndex((line, i) => i > start && line.startsWith(`${indent}- `));
    return lines.slice(start, end < 0 ? undefined : end).join("\n");
}

/** A job's lines before its first checkout, each `- *<name>` replaced by the step it repeats. */
function beforeCheckout(job: Job): string {
    const before = job.block.slice(0, job.block.indexOf("uses: actions/checkout"));
    return before.replace(/- \*([A-Za-z0-9_-]+)/g, (_, name: string) => anchored(job.workflow, name));
}

const label = (job: Job) => `${path.basename(job.workflow)} ${job.name}`;
const selfHosted = jobs().filter((job) => canTakeSelfHosted(job) && job.block.includes("uses: actions/checkout"));
const cases: [string, Job][] = selfHosted.map((job) => [label(job), job]);

describe("a sparse checkout never outlives its job on a self-hosted runner", () => {
    test("the jobs read are those that can take a self-hosted runner", () => {
        const names = selfHosted.map(label);
        expect(names).toEqual(
            expect.arrayContaining([
                "docker-compose.yml build-image",
                "docker-compose.yml unit",
                "docker-compose.yml e2e-desktop",
                "docker-compose.yml test-gpu-stress",
                "docker-compose.yml ci-report",
                "weekly-flake-hunt.yml report",
                "skill-evals.yml evaluate",
            ]),
        );
        // pick-runners checks out sparse, on a GitHub-hosted runner it never shares.
        expect(names).not.toContain("docker-compose.yml pick-runners");
    });

    test.each(cases)("%s checks out the whole tree", (_, job) => {
        expect(job.block).not.toMatch(/^\s+sparse-checkout(-cone-mode)?:/m);
    });

    test.each(cases)("%s forgets a sparse checkout an earlier job left, before its own", (_, job) => {
        const before = beforeCheckout(job);
        for (const line of FORGET) expect(before).toContain(line);
    });
});

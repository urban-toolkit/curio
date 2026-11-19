/**
 * An e2e job draws a page the same way on every runner it lands on.
 *
 * The browser draws a Vega-Lite time axis in its machine's local time. A
 * GitHub-hosted runner and an arcade runner, CPU or GPU, keep UTC, and the
 * baselines are their captures, while utk-gpu and the utk desktops keep
 * America/Chicago:
 * - on a desktop's CPU job, example 04's two charts with a time axis read
 *   0.44% and 0.42% from hosted's captures, while its 44 other chart
 *   close-ups matched byte for byte (run 44431740398);
 * - in test-gpu on utk-gpu and utk-desktop-03, example 26's chart with a time
 *   axis read 0.50% from arcade's capture, its labels six hours apart, while
 *   the 21 other chart close-ups and every map close-up matched byte for byte
 *   (runs 44410619936, 44410636007 and 44410640623).
 * So every job whose browser takes the suite's frames runs in UTC, its pytest
 * and its browser alike, since a test may compute a date the page shows.
 */
import { read } from "./_support/workflowPaths";

const WORKFLOW = ".github/workflows/docker-compose.yml";
/** The jobs whose browser takes the e2e suite's frames: on CPU runners, and test-gpu on GPU runners. */
const E2E_JOBS = ["e2e-desktop", "test-isolated", "test-gpu"];

/** The workflow's jobs, keyed by name, as the text under `jobs:`. */
function jobs(): Map<string, string> {
    const text = read(WORKFLOW);
    const body = text.slice(text.search(/^jobs:\s*$/m));
    const found = new Map<string, string>();
    for (const block of body.split(/^(?= {2}[a-z0-9-]+:\s*$)/m).slice(1)) {
        found.set(block.trim().split(":")[0], block);
    }
    return found;
}

/** A job's own `env:` block: the lines after its `env:` line, up to its next key. */
function jobEnv(name: string): string {
    const text = jobs().get(name);
    if (!text) throw new Error(`${WORKFLOW} has no job ${name}`);
    const lines = text.split("\n");
    const start = lines.findIndex((line) => /^ {4}env:\s*$/.test(line));
    if (start < 0) throw new Error(`${name} has no env: block`);
    const block: string[] = [];
    for (const line of lines.slice(start + 1)) {
        if (/^ {0,4}\S/.test(line)) break;
        block.push(line);
    }
    return block.join("\n");
}

describe("An e2e job's time zone", () => {
    test.each(E2E_JOBS)("%s runs in UTC, as GitHub-hosted and arcade runners do", (name) => {
        expect([name, /^ {6}TZ: UTC\s*$/m.test(jobEnv(name))]).toEqual([name, true]);
    });

    test.each(E2E_JOBS)("no step of %s sets another time zone", (name) => {
        const steps = (jobs().get(name) ?? "").split(/^(?= {6}- )/m).slice(1);
        const setting = steps.filter((step) => /^\s+TZ:|\bTZ=/m.test(step));
        expect([name, setting]).toEqual([name, []]);
    });
});

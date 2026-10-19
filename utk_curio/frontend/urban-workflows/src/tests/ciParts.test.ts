/**
 * Every part a split suite is cut into is a job the Full stack build runs.
 *
 * utk_curio/backend/tests/parts.py holds how many parts each split suite runs
 * in (E2E_DESKTOP_PARTS, BACKEND_UNIT_PARTS), and the backend tests that check
 * the split read them there. The workflow holds the jobs: e2e-desktop's
 * matrix, the unit job's backend entries, pick-runners' keys, and the jobs
 * ci_never_run.py waits for. That check, that every test ran in some job,
 * checks nothing when a job it names sent no results, and a part missing from
 * its list makes the tests only that part runs look unchecked. The backend
 * suite runs in the CI image, which ships no workflow, so this check lives here.
 */
import { read } from "./_support/workflowPaths";

const WORKFLOW = ".github/workflows/docker-compose.yml";
const PARTS = "utk_curio/backend/tests/parts.py";

function constant(name: string): number {
    const match = new RegExp(`^${name}\\s*=\\s*(\\d+)\\s*$`, "m").exec(read(PARTS));
    if (!match) throw new Error(`${PARTS} has no line ${name} = <number>`);
    return Number(match[1]);
}

const upTo = (count: number): number[] => Array.from({ length: count }, (_, i) => i + 1);
const named = (prefix: string, count: number): string[] => upTo(count).map((k) => `${prefix}${k}`);
const byPart = (a: string, b: string): number => Number(/\d+$/.exec(a)?.[0]) - Number(/\d+$/.exec(b)?.[0]);

/** One job of the workflow: its lines from `  <job>:` to the next job. */
function jobBlock(job: string): string {
    const lines = read(WORKFLOW).split("\n");
    const start = lines.findIndex((line) => line === `  ${job}:`);
    if (start < 0) throw new Error(`${WORKFLOW} has no job ${job}`);
    const end = lines.findIndex((line, i) => i > start && /^ {2}[A-Za-z0-9_-]+:\s*$/.test(line));
    return lines.slice(start, end < 0 ? undefined : end).join("\n");
}

/** `{1..14}` as bash expands it in a command. */
function expandBraces(word: string): string[] {
    const match = /^(.*)\{(\d+)\.\.(\d+)\}(.*)$/.exec(word);
    if (!match) return [word];
    const [, head, from, to, tail] = match;
    return upTo(Number(to))
        .filter((k) => k >= Number(from))
        .map((k) => `${head}${k}${tail}`);
}

/** The arguments of the python command that runs `script` in a job, continued lines joined. */
function commandArguments(block: string, script: string): string[] {
    const lines = block.split("\n");
    // Not the sparse checkout that fetches the script, nor a comment naming it.
    const start = lines.findIndex((line) => /^\s*python3?\s/.test(line) && line.includes(script));
    if (start < 0) throw new Error(`no command runs ${script}`);
    let text = "";
    for (const line of lines.slice(start)) {
        const trimmed = line.trim();
        text += ` ${trimmed.replace(/\\$/, "")}`;
        if (!trimmed.endsWith("\\")) break;
    }
    return text
        .slice(text.indexOf(script) + script.length)
        .trim()
        .split(/\s+/)
        .flatMap(expandBraces);
}

describe("the parts of the split suites", () => {
    const e2eParts = constant("E2E_DESKTOP_PARTS");
    const unitParts = constant("BACKEND_UNIT_PARTS");

    test("parts.py splits each suite in more than one part", () => {
        expect(e2eParts).toBeGreaterThan(1);
        expect(unitParts).toBeGreaterThan(1);
    });

    test("e2e-desktop runs one job per part, and each part knows the count", () => {
        const block = jobBlock("e2e-desktop");
        const matrix = /^\s+part:\s*\[([^\]]*)\]\s*$/m.exec(block);
        if (!matrix) throw new Error("e2e-desktop has no part: [...] matrix");
        expect(matrix[1].split(",").map((part) => Number(part.trim()))).toEqual(upTo(e2eParts));
        // k/n with n the matrix's own size.
        expect(block).toContain("CURIO_E2E_PART: ${{ matrix.part }}/${{ strategy.job-total }}");
        expect(block).toContain("format('e2e-desktop-{0}', matrix.part)");
    });

    test("the unit job runs one backend entry per part", () => {
        const block = jobBlock("unit");
        const entries = [
            ...block.matchAll(/-\s*\{\s*name:\s*backend-(\d+),\s*suite:\s*backend,\s*part:\s*"(\d+)\/(\d+)"\s*\}/g),
        ];
        expect(entries.map((entry) => Number(entry[1]))).toEqual(upTo(unitParts));
        expect(entries.map((entry) => `${entry[2]}/${entry[3]}`)).toEqual(
            upTo(unitParts).map((k) => `${k}/${unitParts}`),
        );
        expect(block).toContain("format('unit-{0}', matrix.name)");
    });

    test("pick-runners picks a runner for every part, once", () => {
        const keys = commandArguments(jobBlock("pick-runners"), "scripts/ci_pick_runners.py").filter((word) =>
            /^[a-z][a-z0-9-]*$/.test(word),
        );
        expect(new Set(keys).size).toBe(keys.length);
        expect(keys.filter((key) => key.startsWith("e2e-desktop-")).sort(byPart)).toEqual(
            named("e2e-desktop-", e2eParts),
        );
        expect(keys.filter((key) => key.startsWith("unit-backend-")).sort(byPart)).toEqual(
            named("unit-backend-", unitParts),
        );
    });

    test("ci_never_run.py waits for the results of every part", () => {
        const [folder, ...jobs] = commandArguments(jobBlock("ci-report"), "scripts/ci_never_run.py");
        expect(folder).toBe("inputs");
        expect(new Set(jobs).size).toBe(jobs.length);
        expect(jobs.filter((job) => job.startsWith("e2e-desktop-")).sort(byPart)).toEqual(
            named("e2e-desktop-", e2eParts),
        );
        expect(jobs.filter((job) => job.startsWith("unit-backend-")).sort(byPart)).toEqual(
            named("unit-backend-", unitParts),
        );
    });
});

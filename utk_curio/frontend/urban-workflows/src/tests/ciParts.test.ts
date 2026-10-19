/**
 * Every part a split suite is cut into is a job the Full stack build runs.
 *
 * utk_curio/backend/tests/parts.py holds how many parts each split suite runs
 * in (E2E_DESKTOP_PARTS, BACKEND_UNIT_PARTS), and the backend tests that check
 * the split read them there. The workflow holds the jobs: e2e-desktop's
 * matrix, the unit job's backend entries, the keys of the two runner picks
 * (pick-runners for the jobs that start at once, build-image's last step for
 * the jobs that wait on the image), and the jobs ci_never_run.py waits for.
 * That check, that every test ran in some job, checks nothing when a job it
 * names sent no results, and a part missing from its list makes the tests only
 * that part runs look unchecked. A job whose runs-on reads a key its pick never
 * wrote cannot start at all. The backend suite runs in the CI image, which
 * ships no workflow, so this check lives here.
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

/** Every job of the workflow, in its order. */
function jobNames(): string[] {
    const lines = read(WORKFLOW).split("\n");
    const start = lines.indexOf("jobs:");
    if (start < 0) throw new Error(`${WORKFLOW} has no top-level jobs: block`);
    return lines.slice(start + 1).flatMap((line) => /^ {2}([A-Za-z0-9_-]+):\s*$/.exec(line)?.slice(1, 2) ?? []);
}

/** The value of one of a job's own keys (`runs-on`, `needs`), not a step's. */
function jobKey(block: string, key: string): string {
    return new RegExp(`^ {4}${key}:\\s*(.*)$`, "m").exec(block)?.[1] ?? "";
}

/** The options ci_pick_runners.py takes, each with one value. */
const PICK_OPTIONS = ["--gpu", "--hosted-reserved", "--this-run-except"];

/** The job keys a ci_pick_runners.py command in a job picks for (its CPU ones and each --gpu one), and its options. */
function pickIn(job: string): { keys: string[]; options: Map<string, string[]> } {
    const words = commandArguments(jobBlock(job), "scripts/ci_pick_runners.py");
    const keys: string[] = [];
    const options = new Map<string, string[]>();
    for (let i = 0; i < words.length; i += 1) {
        const word = words[i];
        if (!word.startsWith("--")) {
            keys.push(word);
            continue;
        }
        if (!PICK_OPTIONS.includes(word)) throw new Error(`${job}'s pick has an option this test cannot read: ${word}`);
        i += 1;
        options.set(word, [...(options.get(word) ?? []), words[i]]);
        if (word === "--gpu") keys.push(words[i]);
    }
    return { keys, options };
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

    describe("the two runner picks", () => {
        const early = pickIn("pick-runners");
        const late = pickIn("build-image");

        /** The keys a runs-on reads with `index`: one quoted key, or one per matrix entry. */
        function readKeys(index: string): string[] {
            const quoted = /^'([a-z0-9-]+)'$/.exec(index);
            if (quoted) return [quoted[1]];
            // The matrices these expand are checked against parts.py above.
            const perEntry: Record<string, string[]> = {
                "format('e2e-desktop-{0}', matrix.part)": named("e2e-desktop-", e2eParts),
                "format('unit-{0}', matrix.name)": named("unit-backend-", unitParts),
            };
            if (!(index in perEntry)) {
                throw new Error(`a runs-on reads its runner by ${index}, which this test cannot expand`);
            }
            return perEntry[index];
        }

        test("pick-runners and build-image's last step pick a runner for every part, each key once", () => {
            const keys = [...early.keys, ...late.keys];
            expect(keys.filter((key) => !/^[a-z][a-z0-9-]*$/.test(key))).toEqual([]);
            // Once across both picks: no key in both, none twice in one.
            expect(new Set(keys).size).toBe(keys.length);
            expect(keys.filter((key) => key.startsWith("e2e-desktop-")).sort(byPart)).toEqual(
                named("e2e-desktop-", e2eParts),
            );
            expect(keys.filter((key) => key.startsWith("unit-backend-")).sort(byPart)).toEqual(
                named("unit-backend-", unitParts),
            );
            // In the first pick, so that a run whose image fails to build still gets its report.
            expect(early.keys).toContain("ci-report");
        });

        test("each job reads its runner from the pick that lists its key", () => {
            const reads: Record<string, string[]> = { "pick-runners": [], "build-image": [] };
            const pickRead = /fromJSON\(needs\.([a-z-]+)\.outputs\.runners\)\[([^\]]+)\]/g;
            for (const job of jobNames()) {
                const block = jobBlock(job);
                // A job that waits for the image reads build-image's pick, made as it is about to start.
                const expected = /\bbuild-image\b/.test(jobKey(block, "needs")) ? "build-image" : "pick-runners";
                for (const [, pick, index] of jobKey(block, "runs-on").matchAll(pickRead)) {
                    expect(`${job} reads ${pick}`).toBe(`${job} reads ${expected}`);
                    reads[pick].push(...readKeys(index));
                }
            }
            // Every key a pick writes is read, and every key read was written.
            expect([...reads["pick-runners"]].sort()).toEqual([...early.keys].sort());
            expect([...reads["build-image"]].sort()).toEqual([...late.keys].sort());
        });

        test("build-image's pick is its last step and runs whether the image was built or reused", () => {
            const block = jobBlock("build-image");
            const steps = block.split(/\n(?= {6}- )/);
            const last = steps[steps.length - 1];
            expect(last).toContain("scripts/ci_pick_runners.py");
            expect(last).toMatch(/^ {8}id: pick$/m);
            // No condition: a reused image skips the build step, and the jobs still need runners.
            expect(last).not.toMatch(/^ {8}if:/m);
            expect(block).toMatch(/^ {6}runners: \$\{\{ steps\.pick\.outputs\.runners \}\}$/m);
        });

        test("build-image's pick counts its run's own jobs but build-image, by the name the jobs API gives it", () => {
            expect(late.options.get("--this-run-except")).toEqual(["build-image"]);
            expect(early.options.has("--this-run-except")).toBe(false);
            // The jobs API names a job by its `name:` when it has one, and by its key otherwise.
            expect(jobBlock("build-image")).not.toMatch(/^ {4}name:/m);
        });

        test("each pick holds back a hosted slot for each hosted-only job it cannot count", () => {
            // The jobs that run hosted whatever a pick says, and the pick each one's
            // slot is held back in: the first for those that start with the run, the
            // second for those that wait for the image and so are not in the jobs API yet.
            const hostedOnly = jobNames()
                .filter((job) => job !== "pick-runners")
                .flatMap((job) => {
                    const block = jobBlock(job);
                    const runsOn = jobKey(block, "runs-on");
                    const entry = /matrix\.\w+ == '([^']*)' && 'ubuntu-latest'/.exec(runsOn);
                    const name = runsOn === "ubuntu-latest" ? job : entry ? `${job} (${entry[1]})` : "";
                    const pick = /\bbuild-image\b/.test(jobKey(block, "needs")) ? "build-image" : "pick-runners";
                    return name ? [[name, pick]] : [];
                });
            expect(hostedOnly).toEqual([
                ["unit (sandbox)", "build-image"],
                ["preview-runner", "pick-runners"],
                ["test-desktop-stress", "build-image"],
            ]);
            expect(early.options.get("--hosted-reserved")).toEqual(["1"]);
            expect(late.options.get("--hosted-reserved")).toEqual(["2"]);
        });
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

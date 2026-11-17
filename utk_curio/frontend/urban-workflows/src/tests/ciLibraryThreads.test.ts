/**
 * A CI stack runs node code on its runner's share of the CPUs.
 *
 * Torch, OpenBLAS and the other OpenMP libraries start a thread per CPU they
 * see, and onnxruntime one per core. An arcade runner, CPU or GPU, is a
 * container with no CPU quota that shows all 192 CPUs of a server its 44
 * runners share, so a node there ran on 96 threads beside every other job's:
 * example 28's training past the sandbox's 300 s in test-isolated's stack (run
 * 42230248452), and example 10's Image Segmentation for 129 s in e2e-desktop's
 * (run 44027626125), where a quiet runner takes 11 s.
 *
 * So each job whose stack runs the shipped dataflows' nodes sizes the stack's
 * library threads before the stack starts (CURIO_CI_LIBRARY_THREADS: the
 * runner's CPUs, at most 8), and its compose overlay hands the count on as
 * OMP_NUM_THREADS, which the code that makes an onnxruntime session hands
 * onnxruntime (tested in the backend and sandbox suites). After the tests,
 * scripts/ci_library_threads.py (tested in the backend suite) fails the job
 * unless a node of the stack got the count.
 *
 * The backend suite runs in the image, which ships no workflow or compose
 * file, so these checks live here.
 */
import { read } from "./_support/workflowPaths";

const WORKFLOW = ".github/workflows/docker-compose.yml";
/** The jobs whose stack runs the shipped dataflows' nodes. */
const SIZED = ["test-gpu", "e2e-desktop", "test-isolated"];
/** Those whose stack is docker-compose.ci.yml's, which passes on the job's own OMP_NUM_THREADS. */
const THROUGH_THE_CI_OVERLAY = ["test-gpu", "e2e-desktop"];
const SIZING = "Size the stack's library threads to this runner";
const CHECK = "run: python3 scripts/ci_library_threads.py";
const TESTS = "bash scripts/ci_repeat.sh bash scripts/test.sh --e2e-only";

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

/** One job's steps, in their order, each from its `- ` line to the next step's. */
function steps(name: string): string[] {
    const text = jobs().get(name);
    if (!text) throw new Error(`${WORKFLOW} has no job ${name}`);
    return text.split(/^(?= {6}- )/m).filter((step) => step.startsWith("      - "));
}

describe("A CI stack's library threads", () => {
    test.each(SIZED)("%s sizes them to its runner, at most 8, before its stack starts", (name) => {
        const all = steps(name);
        const sizing = all.findIndex((step) => step.includes(SIZING));
        expect([name, sizing >= 0]).toEqual([name, true]);
        expect(all[sizing]).toContain('threads=$(nproc); [ "$threads" -gt 8 ] && threads=8\n');
        expect(all[sizing]).toContain('echo "CURIO_CI_LIBRARY_THREADS=$threads" >> "$GITHUB_ENV"\n');
        const starts = all.findIndex((step) =>
            /uses: \.\/\.github\/actions\/start-stack|docker compose -p \S+ up -d/.test(step),
        );
        expect(starts).toBeGreaterThan(-1);
        expect(sizing).toBeLessThan(starts);
    });

    test.each(SIZED)("%s checks a node of its stack after its tests, whatever they did", (name) => {
        const all = steps(name);
        const tests = all.findIndex((step) => step.includes(TESTS));
        const check = all.findIndex((step) => step.includes(CHECK));
        expect(tests).toBeGreaterThan(-1);
        expect([name, check > tests]).toEqual([name, true]);
        expect(all[check]).toMatch(/^ {8}if: \$\{\{ !cancelled\(\)/m);
    });

    test.each(THROUGH_THE_CI_OVERLAY)("%s hands its stack the count as OMP_NUM_THREADS", (name) => {
        expect(jobs().get(name)).toMatch(/^ {6}COMPOSE_FILE: docker-compose\.yml:docker-compose\.ci\.yml(:|$)/m);
        const sizing = steps(name).find((step) => step.includes(SIZING));
        expect([name, sizing !== undefined]).toEqual([name, true]);
        expect(sizing).toContain('echo "OMP_NUM_THREADS=$threads" >> "$GITHUB_ENV"\n');
    });

    test("the overlays pass the count on to the stack", () => {
        // docker-compose.ci.yml passes on the job's own variable, so a job that sets none keeps its stack's default.
        expect(read("docker-compose.ci.yml")).toMatch(/^ {6}- OMP_NUM_THREADS$/m);
        expect(read("docker-compose.ci-isolated.yml")).toMatch(
            /^ {6}- OMP_NUM_THREADS=\$\{CURIO_CI_LIBRARY_THREADS:\?[^}\n]+\}$/m,
        );
    });

    test("the jobs that size their stack's library threads are those", () => {
        const sizing = Array.from(jobs())
            .filter(([, text]) => text.includes("CURIO_CI_LIBRARY_THREADS="))
            .map(([name]) => name);
        expect(sizing.sort()).toEqual([...SIZED].sort());
    });
});

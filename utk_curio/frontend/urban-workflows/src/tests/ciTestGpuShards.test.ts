/**
 * test-gpu runs as many e2e workers as the runner's memory holds, and at
 * least two backend and sandbox pairs (shards): test_shard_isolation_e2e
 * needs a second shard, but not a second worker. scripts/ci_memory_budget.py
 * writes the workers to CURIO_E2E_PARALLEL and, when the shards outnumber
 * them, the shards to CURIO_E2E_SHARDS (tested in the backend suite). So the
 * job must start the shards from CURIO_E2E_SHARDS: started from the workers,
 * a runner that holds one worker (utk-desktop-02) would start no second shard,
 * and the isolation test would run in no job. Two workers there took more
 * memory than the container's limit left them, and the kernel killed a
 * sandbox at the limit (run 40700358711, 10-28).
 *
 * A test sees such a kill only as a server that stopped answering, so
 * stop-stack reads the container's memory.events and names the kills before
 * it removes the containers.
 *
 * The backend suite runs in the image, which ships no workflow, so these
 * checks live here.
 */
import { read } from "./_support/workflowPaths";

const WORKFLOW = ".github/workflows/docker-compose.yml";
const STOP_STACK = ".github/actions/stop-stack/action.yml";

/** One job of the workflow, as the text under its name. */
function job(name: string): string {
    const text = read(WORKFLOW);
    const body = text.slice(text.search(/^jobs:\s*$/m));
    const block = body.split(/^(?= {2}[a-z0-9-]+:\s*$)/m).find((b) => b.startsWith(`  ${name}:`));
    if (!block) throw new Error(`${WORKFLOW} has no job ${name}`);
    return block;
}

/** The step of a job's text whose name contains `name`. */
function step(jobText: string, name: string): string {
    const steps = jobText.split(/^(?= {6}- )/m).filter((s) => s.startsWith("      - "));
    const found = steps.find((s) => s.includes(`name: `) && s.split("\n")[0].includes(name));
    if (!found) throw new Error(`no step named ${JSON.stringify(name)}`);
    return found;
}

describe("test-gpu's shards and workers", () => {
    test("it starts the shards the budget asks for, and runs pytest on the workers", () => {
        const shards = step(job("test-gpu"), "Start the extra e2e shards");
        expect(shards).toContain('shards="${CURIO_E2E_SHARDS:-$CURIO_E2E_PARALLEL}"');
        // One loop starts them and one waits for each.
        expect(shards.match(/for k in \$\(seq 1 \$\(\(shards - 1\)\)\); do/g)).toHaveLength(2);
        expect(shards).not.toContain("CURIO_E2E_PARALLEL - 1");
        const e2e = step(job("test-gpu"), "Run the WebGPU e2e tests");
        expect(e2e).toContain('--parallel "$CURIO_E2E_PARALLEL"');
    });
});

describe("stop-stack", () => {
    test("names the processes the kernel killed at the memory limit before the containers go", () => {
        const text = read(STOP_STACK);
        const kills = text.indexOf("cat /sys/fs/cgroup/memory.events");
        expect(kills).toBeGreaterThan(-1);
        expect(text).toContain('scripts/ci_memory_budget.py" kills');
        expect(kills).toBeLessThan(text.indexOf("down -v --remove-orphans"));
    });
});

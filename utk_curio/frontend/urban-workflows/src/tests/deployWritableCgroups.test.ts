/**
 * Each isolated node's memory is a cgroup at its budget, which a container
 * may arrange only when Docker gives it writable cgroups and a private cgroup
 * namespace (docker-compose.deploy.yml). A Docker older than Engine 28 refuses
 * the option and the stack does not start, so each deploy job checks the
 * engine before it stops the running stack. A stack whose nodes fell back to
 * the address-space cap still starts and serves, so each job fails unless the
 * new stack's /version says cgroup. Stable deploys a release, whose overlay
 * may not ask for them yet: each job checks what its checkout's overlay asks.
 */
import { read } from "./_support/workflowPaths";

test("the deploy overlay asks for a private cgroup namespace and writable cgroups", () => {
    const overlay = read("docker-compose.deploy.yml");
    expect(overlay).toMatch(/^ {4}cgroup: private$/m);
    expect(overlay).toMatch(/^ {4}security_opt:\n {6}- writable-cgroups=true$/m);
});

describe("Each deploy job", () => {
    const text = read(".github/workflows/deploy.yml");
    const jobs = text.split(/^ {2}deploy-(?:dev|stable):$/m).slice(1);

    test("there is one for each stack", () => {
        expect(jobs).toHaveLength(2);
    });

    test.each([0, 1])("job %s checks Docker Engine 28 before it stops the running stack, when its overlay asks for writable cgroups", (index) => {
        const job = jobs[index];
        const asks = job.indexOf("if grep -q -e 'writable-cgroups=true' docker-compose.deploy.yml; then");
        const engine = job.indexOf("engine_version=\"$(docker version --format '{{.Server.Version}}')\"");
        const stop = job.indexOf('echo "=== stopping the old stack ==="');
        expect(asks).toBeGreaterThan(-1);
        expect(engine).toBeGreaterThan(asks);
        expect(stop).toBeGreaterThan(engine);
        expect(job.slice(engine, stop)).toContain(`"$(printf '%s\\n' 28.0.0 "$engine_version" | sort -V | head -n1)" != 28.0.0`);
    });

    test.each([0, 1])("job %s fails unless the new stack's /version says cgroup", (index) => {
        const job = jobs[index];
        const asked = job.indexOf('version_json="$(docker compose');
        const check = job.indexOf(`*'"memory_limit":"cgroup"'*)`);
        expect(asked).toBeGreaterThan(-1);
        expect(check).toBeGreaterThan(asked);
        expect(job.slice(check)).toMatch(/\*\)\n[^\n]*::error::the deployed stack's nodes get no cgroup at their budget[\s\S]*?exit 1/);
    });
});

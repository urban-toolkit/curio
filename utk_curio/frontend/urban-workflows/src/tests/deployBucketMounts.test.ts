/**
 * Both stacks run the bucket mount service (docker-compose.bucket-mounts.yml)
 * for a release whose launcher has its flags, which each job detects as it
 * detects --model-weights-dir. Each stack mounts in a folder of its own
 * outside its checkout, which its site file binds into both containers. Each
 * bind is written in full: Compose keeps the later of two binds of one target
 * whole, so a bind without the overlay's propagation would hide the mounts
 * from Curio. Before the old stack stops, each job checks the host (FUSE, a
 * shared /srv, the AppArmor profile loaded and the checkout's) and names the
 * command to run; once the stack is up, the service must be healthy and
 * Curio's self-test of it passed, or the deploy fails. The files are read as
 * text, as deployMediaCacheFile.test.ts reads deploy.yml.
 */
import { flowFields, services, value, volumes } from "./_support/composeFile";
import { read } from "./_support/workflowPaths";

const WORKFLOW = ".github/workflows/deploy.yml";
const OVERLAY = "docker-compose.bucket-mounts.yml";
const PROFILE = "scripts/bucket-mounts/curio-bucket-mounts.apparmor";
const INSTALLED = "/etc/apparmor.d/curio-bucket-mounts";
const MODULE = "utk_curio/backend/app/discovery/infrastructure/bucket_mounts.py";

const text = read(WORKFLOW);
const jobs = text.split(/^ {2}deploy-(?:dev|stable):$/m).slice(1);
/** Each stack's name, its Compose project and its job's text. */
const STACKS: Array<[string, string, string]> = [
    ["dev", "curio-dev", jobs[0] ?? ""],
    ["stable", "curio", jobs[1] ?? ""],
];

const escape = (literal: string): string => literal.replace(/[.*+?^${}()|[\]\\/]/g, "\\$&");

/** Where `needle` is in `haystack`, which must hold it once. */
function once(haystack: string, needle: string): number {
    const first = haystack.indexOf(needle);
    expect(first).toBeGreaterThan(-1);
    expect(haystack.indexOf(needle, first + 1)).toBe(-1);
    return first;
}

/** The text of the `if [ -n "$mounts_args" ]` block whose first line is `first`. */
function guarded(job: string, first: string): string {
    const pattern = new RegExp(`^( +)if \\[ -n "\\$mounts_args" \\]; then\\n\\1 {2}${escape(first)}\\n[\\s\\S]*?\\n\\1fi$`, "m");
    const match = pattern.exec(job);
    expect(match).not.toBeNull();
    return match?.[0] ?? "";
}

/** The overlay's bind of `target` in its service `name`, flattened. */
function overlayBind(name: string, target: string): Record<string, string> {
    const found = volumes(services(OVERLAY).get(name) ?? []).filter((volume) => volume.target === target);
    expect(found).toHaveLength(1);
    return found[0] ?? {};
}

/** A number of the backend's bucket_mounts.py. */
function moduleNumber(name: string): number {
    const match = new RegExp(`^${name} = (\\d+)$`, "m").exec(read(MODULE));
    if (!match) throw new Error(`${MODULE} has no line ${name} = <number>`);
    return Number(match[1]);
}

describe("The deploy's bucket mount service", () => {
    test("the two jobs are dev's and stable's", () => {
        expect(jobs).toHaveLength(2);
        expect(STACKS[0][2]).toContain("\n          cd /srv/curio-dev\n");
        expect(STACKS[1][2]).toContain("\n          cd /srv/curio\n");
    });

    test("each stack turns it on only for a launcher that declares its flags", () => {
        const main = read("utk_curio/main.py");
        expect(main).toMatch(/add_argument\(\s*"--bucket-mounts-dir"/);
        expect(main).toMatch(/add_argument\(\s*"--bucket-mount-socket"/);
        // The folder the overlay binds into Curio's container, and the socket
        // in the control volume both containers share.
        const curio = services(OVERLAY).get("curio") ?? [];
        expect(overlayBind("curio", "/bucket-mounts").type).toBe("bind");
        const control = volumes(curio).find((volume) => volume.source === "bucket-mounts-control");
        const socket = `${control?.target}/rc.sock`;
        expect(socket).toBe("/run/curio-bucket-mounts/rc.sock");
        const flags = `, "--bucket-mounts-dir", "/bucket-mounts", "--bucket-mount-socket", "${socket}"`;
        for (const [, , job] of STACKS) {
            const detect = new RegExp(
                `^( +)if grep -q -e '"--bucket-mounts-dir"' utk_curio\\/main\\.py; then\\n\\1 {2}mounts_args='${escape(flags)}'\\n\\1fi$`,
                "gm",
            );
            expect(job.match(detect)).toHaveLength(1);
            const unset = once(job, 'mounts_args=""');
            expect(unset).toBeLessThan(job.indexOf(`grep -q -e '"--bucket-mounts-dir"'`));
        }
        expect(text.match(/mounts_args='/g)).toHaveLength(2);
    });

    test("each stack's command line passes them, after setting them", () => {
        for (const [, , job] of STACKS) {
            const command = job.search(/printf ' {4}command: \[[^\n]*"\$mounts_args" >> docker-compose\.site\.yml\n/);
            expect(command).toBeGreaterThan(-1);
            expect(job.indexOf(`grep -q -e '"--bucket-mounts-dir"'`)).toBeLessThan(command);
        }
    });

    test("COMPOSE_FILE takes the overlay after the deploy's and before the site file, only with the flags", () => {
        for (const [, project, job] of STACKS) {
            const exports = [...job.matchAll(/^ *export COMPOSE_FILE=(\S+)$/gm)].map((match) => match[1]);
            expect(exports).toEqual([
                "docker-compose.yml:docker-compose.deploy.yml",
                "$COMPOSE_FILE:docker-compose.bucket-mounts.yml",
                "$COMPOSE_FILE:docker-compose.site.yml",
            ]);
            expect(job).toMatch(
                /^( +)if \[ -n "\$mounts_args" \]; then\n\1 {2}export COMPOSE_FILE=\$COMPOSE_FILE:docker-compose\.bucket-mounts\.yml\n\1fi\n\1export COMPOSE_FILE=\$COMPOSE_FILE:docker-compose\.site\.yml$/m,
            );
            expect(job.indexOf("export COMPOSE_FILE=$COMPOSE_FILE:docker-compose.site.yml")).toBeLessThan(
                once(job, `docker compose -p ${project} build --no-cache`),
            );
        }
    });

    test("each stack's site file binds its own folder outside its checkout into both containers, each bind as the overlay's but its source", () => {
        const curioBind = overlayBind("curio", "/bucket-mounts");
        const serviceBind = overlayBind("bucket-mounts", "/mounts");
        // The propagation that carries a mount from the service to Curio.
        expect(curioBind).toMatchObject({ read_only: "true", "bind.propagation": "rslave", "bind.create_host_path": "true" });
        expect(serviceBind).toMatchObject({ "bind.propagation": "rshared", "bind.create_host_path": "true" });
        for (const [stack, , job] of STACKS) {
            expect(job.match(/^ +mounts_dir=.*$/gm)).toEqual([expect.stringMatching(new RegExp(`^ +mounts_dir=/srv/curio-bucket-mounts/${stack}$`))]);
            const curio = /^( +)if \[ -n "\$mounts_args" \]; then\n\1 {2}curio_volumes="\$\{curio_volumes:\+\$curio_volumes, \}(\{[^"\n]*\})"\n\1fi$/m.exec(job);
            expect(curio).not.toBeNull();
            expect(flowFields(curio?.[2] ?? "")).toEqual({ ...curioBind, source: "$mounts_dir" });
            const service = /^( +)if \[ -n "\$mounts_args" \]; then\n\1 {2}printf ' {2}bucket-mounts:\\n {4}volumes: \[(\{[^\]\n]*\})\]\\n' "\$mounts_dir" >> docker-compose\.site\.yml\n\1fi$/m.exec(job);
            expect(service).not.toBeNull();
            expect(flowFields(service?.[2] ?? "")).toEqual({ ...serviceBind, source: "%s" });
        }
        // Docker makes the folder, root's: the service cannot write in one of
        // the deploy account's.
        expect(text).not.toMatch(/mkdir[^\n]*curio-bucket-mounts/);
    });

    test("each site file writes Curio's keys, then the service's, then the top-level secrets", () => {
        for (const [, , job] of STACKS) {
            const order = [
                job.search(/printf ' {4}command: \[/),
                once(job, `printf '    volumes: [%s]\\n' "$curio_volumes" >> docker-compose.site.yml`),
                once(job, "printf '    secrets: [curio_llm_endpoint]\\n' >> docker-compose.site.yml"),
                once(job, "printf '  bucket-mounts:\\n"),
                once(job, "printf 'secrets:\\n  curio_llm_endpoint:\\n    file: ./.secrets/llm-endpoint\\n' >> docker-compose.site.yml"),
                once(job, "export COMPOSE_FILE=$COMPOSE_FILE:docker-compose.site.yml"),
            ];
            expect(order[0]).toBeGreaterThan(-1);
            expect([...order].sort((a, b) => a - b)).toEqual(order);
        }
    });

    test("before the old stack stops, each job checks the host and names the command to run", () => {
        const image = value(services(OVERLAY).get("bucket-mounts") ?? [], "image");
        const imageLines = read(OVERLAY).split("\n").filter((line) => /^ {4}image: /.test(line));
        expect(imageLines).toEqual([`    image: ${image}`]);
        expect(read(OVERLAY)).toMatch(/^ {6}- apparmor=curio-bucket-mounts$/m);
        expect(read(PROFILE)).toMatch(/^profile curio-bucket-mounts flags=/m);
        // The fix is DEPLOYMENT.md's install and load, from the job's checkout.
        const guide = read("docs/DEPLOYMENT.md");
        expect(guide).toContain(`sudo install -m 644 ${PROFILE} ${INSTALLED}\n`);
        expect(guide).toContain(`sudo apparmor_parser -r -W ${INSTALLED}\n`);
        const fix = `profile_fix="sudo install -m 644 $PWD/${PROFILE} ${INSTALLED} && sudo apparmor_parser -r -W ${INSTALLED}"`;
        for (const [, project, job] of STACKS) {
            const checks = guarded(job, "if [ ! -c /dev/fuse ]; then");
            const at = job.indexOf(checks);
            expect(job.indexOf(`grep -q -e '"--bucket-mounts-dir"'`)).toBeLessThan(at);
            expect(at).toBeLessThan(once(job, `docker compose -p ${project} build --no-cache`));
            expect(at).toBeLessThan(once(job, `docker compose -p ${project} down`));
            expect(checks).toContain("echo \"::error::/dev/fuse is not a character device, and the bucket mount service needs it. Load FUSE as root: sudo modprobe fuse\"\n");
            expect(checks).toContain('srv_propagation="$(findmnt -n -o PROPAGATION -T /srv || true)"');
            expect(checks).toMatch(/case "\$srv_propagation" in\n +\*shared\*\)\n +;;\n +\*\)\n +echo "::error::[^\n]*Make it shared as root: sudo mount --make-shared \$\(findmnt -n -o TARGET -T \/srv\)"\n +exit 1\n/);
            expect(checks).toContain(fix);
            expect(checks).toContain(`mounts_image="$(sed -n 's/^    image: //p' ${OVERLAY})"`);
            expect(checks).toContain(
                'if ! docker image inspect "$mounts_image" > /dev/null 2>&1 && ! docker pull -q "$mounts_image" > /dev/null < /dev/null; then',
            );
            expect(checks).toContain(
                'if ! profile_run="$(docker run --rm --network none --security-opt apparmor=curio-bucket-mounts --entrypoint /bin/true "$mounts_image" 2>&1 < /dev/null)"; then',
            );
            expect(checks).toContain(`if ! cmp -s ${PROFILE} ${INSTALLED}; then`);
            // The two profile checks name the fix; every failure ends the job.
            expect(checks.match(/Load the profile as root: \$profile_fix"|Install and load the checkout's as root: \$profile_fix"/g)).toHaveLength(2);
            const errors = checks.match(/echo "::error::/g) ?? [];
            expect(errors).toHaveLength(5);
            expect(checks.match(/^ +exit 1$/gm)).toHaveLength(errors.length);
            for (const error of checks.split("\n").filter((line) => line.includes('echo "::error::'))) {
                const after = checks.slice(checks.indexOf(error) + error.length + 1).split("\n")[0];
                expect(after.trim()).toBe("exit 1");
            }
        }
    });

    test("once the stack is up, each job fails unless the service is healthy and Curio's self-test of it passed", () => {
        // The monitor route, its deployment line and the states it reads.
        const routes = read("utk_curio/backend/app/monitor/routes.py");
        expect(routes).toContain('Blueprint("monitor", __name__, url_prefix="/api/monitor")');
        expect(routes).toContain('@monitor_bp.route("", methods=["GET"])');
        expect(routes).toContain('"deployment": _deployment(sandbox),');
        expect(routes).toContain('"bucketMounts": bucket_mounts["state"],');
        expect(routes).toContain('"bucketMountsProblem": bucket_mounts["problem"],');
        const check = read("utk_curio/backend/app/discovery/application/bucket_mount_check.py");
        for (const state of ["none", "pending", "passed", "unavailable"]) {
            expect(check).toContain(`{"state": "${state}"`);
        }
        expect(read("docker-compose.deploy.yml")).toMatch(/^ {6}- --backend-port\n {6}- "5002"$/m);
        const program =
            "python -c 'import json, urllib.request; d = json.load(urllib.request.urlopen(\"http://127.0.0.1:5002/api/monitor\", timeout=10))[\"deployment\"]; " +
            'print(d["bucketMounts"] + (": " + d["bucketMountsProblem"] if d["bucketMountsProblem"] else ""))\' \\';
        // Longer than the self-test's wait for the socket and one slow call and read.
        const least = moduleNumber("SERVICE_WAIT_SECONDS") + moduleNumber("CALL_TIMEOUT") + moduleNumber("READ_TIMEOUT");
        for (const [, project, job] of STACKS) {
            const wait = guarded(job, 'echo "=== bucket mounts ==="');
            const at = job.indexOf(wait);
            expect(once(job, `docker compose -p ${project} up -d --force-recreate --remove-orphans`)).toBeLessThan(at);
            expect(once(job, 'echo "=== waiting for health ==="')).toBeLessThan(at);
            expect(once(job, 'echo "=== node execution isolation ==="')).toBeLessThan(at);
            expect(at).toBeLessThan(once(job, 'echo "=== docker ps (post-deploy) ==="'));
            const deadline = /deadline=\$\(\(SECONDS \+ (\d+)\)\)/.exec(wait);
            expect(Number(deadline?.[1])).toBeGreaterThanOrEqual(least);
            expect(wait).toContain(
                `mounts_health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$(docker compose -p ${project} ps -a -q bucket-mounts)" 2>/dev/null || echo missing)"`,
            );
            expect(wait).toContain(`mounts_line="$(docker compose -p ${project} exec -T curio \\\n`);
            expect(wait).toContain(`${program}\n`);
            expect(wait).toContain('mounts_state="${mounts_line%%:*}"');
            expect(wait).toMatch(
                /if \[ "\$mounts_health" = "healthy" \] && \[ "\$mounts_state" = "passed" \]; then\n +echo "OK: [^\n]*"\n +break\n/,
            );
            expect(wait).toMatch(
                /if \[ "\$mounts_state" = "unavailable" \] \|\| \[ "\$mounts_state" = "none" \] \|\| \[ "\$SECONDS" -ge "\$deadline" \]; then\n +echo "::error::[^\n]*"\n/,
            );
            expect(wait).toContain(`docker compose -p ${project} logs --no-color --tail=100 bucket-mounts || true\n`);
            expect(wait.match(/^ +exit 1$/gm)).toHaveLength(1);
            expect(wait).toMatch(/^ +sleep 5\n +done$/m);
        }
    });

    test("every docker run and docker compose exec of the checks reads /dev/null, so none takes the rest of the script", () => {
        for (const [, , job] of STACKS) {
            const blocks = [guarded(job, "if [ ! -c /dev/fuse ]; then"), guarded(job, 'echo "=== bucket mounts ==="')];
            const commands = blocks
                .join("\n")
                .replace(/\\\n\s*/g, " ")
                .split("\n")
                .filter((line) => /docker run |docker compose [^\n]* exec /.test(line));
            expect(commands).toHaveLength(3);
            for (const command of commands) {
                expect(command).toContain("< /dev/null");
            }
        }
    });
});

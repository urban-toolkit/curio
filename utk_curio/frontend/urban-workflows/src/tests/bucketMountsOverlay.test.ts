/**
 * docker-compose.bucket-mounts.yml, the overlay a deployment adds for its
 * bucket mount service (docs/ARCHITECTURE.md, "Bucket mounts"). Only the
 * service holds FUSE's privileges, and it drops the rest; it is only on its
 * internal network; its image is pinned; the mounts reach Curio's container
 * read-only; and the overlay agrees with the backend's constants
 * (discovery/infrastructure/bucket_mounts.py) and the service's start script.
 * The backend suite runs in the CI image, which ships no compose file, so
 * these checks live here. The files are read as text, as
 * deployMediaCacheFile.test.ts reads deploy.yml.
 */
import * as fs from "fs";
import { REPO_ROOT, read } from "./_support/workflowPaths";
import { block, codeLines, environment, scalars, services, value, volumes } from "./_support/composeFile";

const OVERLAY = "docker-compose.bucket-mounts.yml";
const MODULE = "utk_curio/backend/app/discovery/infrastructure/bucket_mounts.py";
const SERVICE_SCRIPT = "scripts/bucket-mounts/service.sh";

/** A constant of the backend's bucket_mounts.py: a plain string, or a number. */
function pythonConstant(name: string): string {
    const match = new RegExp(`^${name} = (.+)$`, "m").exec(read(MODULE));
    if (!match) throw new Error(`${MODULE} has no line ${name} = ...`);
    const literal = match[1].trim();
    const quoted = /^"([^"\\]*)"$/.exec(literal);
    if (quoted) return quoted[1];
    if (/^\d+$/.test(literal)) return literal;
    throw new Error(`${MODULE}: ${name} = ${literal} is neither a plain string nor a number`);
}

describe("the bucket mount service's overlay", () => {
    const overlay = services(OVERLAY);
    const service = overlay.get("bucket-mounts") ?? [];
    const curio = overlay.get("curio") ?? [];

    test("it holds the service, and additions to Curio's container", () => {
        expect([...overlay.keys()].sort()).toEqual(["bucket-mounts", "curio"]);
        expect(value(curio, "image")).toBeUndefined();
    });

    test("only its bucket-mounts service holds /dev/fuse, SYS_ADMIN or an AppArmor profile, in any compose file", () => {
        const files = fs.readdirSync(REPO_ROOT).filter((name) => /^docker-compose.*\.ya?ml$/.test(name));
        expect(files).toContain(OVERLAY);
        expect(files.length).toBeGreaterThan(5);
        const privileged: string[] = [];
        for (const file of files) {
            for (const [name, lines] of services(file)) {
                if (lines.some((line) => /\/dev\/fuse|SYS_ADMIN|apparmor/i.test(line))) {
                    privileged.push(`${file}: ${name}`);
                }
            }
        }
        expect(privileged).toEqual([`${OVERLAY}: bucket-mounts`]);
        expect(scalars(service, "devices")).toEqual(["/dev/fuse:/dev/fuse"]);
        expect(scalars(service, "cap_add")).toEqual(["SYS_ADMIN"]);
        expect(scalars(service, "security_opt")).toContain("apparmor=curio-bucket-mounts");
    });

    test("the service drops every other capability, and runs no-new-privileges on a read-only root", () => {
        expect(scalars(service, "cap_drop")).toEqual(["ALL"]);
        expect(scalars(service, "security_opt")).toContain("no-new-privileges:true");
        expect(value(service, "read_only")).toBe("true");
        expect(value(service, "mem_limit")).toBeDefined();
        expect(value(service, "pids_limit")).toBeDefined();
    });

    test("the service is only on its network, which is internal, and Curio's container on both", () => {
        expect(scalars(service, "networks")).toEqual(["bucket-mounts"]);
        expect(scalars(curio, "networks")).toEqual(["default", "bucket-mounts"]);
        const network = block(block(codeLines(read(OVERLAY)), "networks", 0), "bucket-mounts", 2);
        expect(network).toContain("    internal: true");
    });

    test("its image is a release of rclone, pinned by its digest", () => {
        expect(value(service, "image")).toMatch(/^rclone\/rclone:\d+\.\d+\.\d+@sha256:[0-9a-f]{64}$/);
    });

    test("Curio's container binds the mounts folder read-only and rslave, the service rshared", () => {
        expect(volumes(service)).toContainEqual({
            type: "bind",
            source: "./bucket-mounts",
            target: pythonConstant("SERVICE_MOUNTS"),
            "bind.propagation": "rshared",
            "bind.create_host_path": "true",
        });
        expect(volumes(curio)).toContainEqual({
            type: "bind",
            source: "./bucket-mounts",
            target: "/bucket-mounts",
            read_only: "true",
            "bind.propagation": "rslave",
            "bind.create_host_path": "true",
        });
        expect(volumes(curio).filter((volume) => volume.source === "./bucket-mounts")).toHaveLength(1);
    });

    test("both containers share the control volume, where the service's socket is", () => {
        const control = { type: "volume", source: "bucket-mounts-control", target: "/run/curio-bucket-mounts" };
        expect(volumes(service)).toContainEqual(control);
        expect(volumes(curio)).toContainEqual(control);
        expect(block(service, "healthcheck", 4).join("\n")).toContain('"--unix-socket", "/run/curio-bucket-mounts/rc.sock", "rc/noop"');
        const script = read(SERVICE_SCRIPT);
        expect(script).toContain("CONTROL=/run/curio-bucket-mounts\n");
        expect(script).toContain('--rc-addr "unix://$CONTROL/rc.sock"');
        expect(script).toContain('chmod 0700 "$CONTROL"');
    });

    test("its proxy is the backend's port", () => {
        expect(environment(service, "HTTPS_PROXY")).toBe(`http://curio:${pythonConstant("PROXY_PORT")}`);
    });

    test("it starts with the start script, bound read-only from the checkout", () => {
        expect(value(service, "entrypoint")).toBe('["/bin/sh", "/opt/curio-bucket-mounts/service.sh"]');
        expect(volumes(service)).toContainEqual({
            type: "bind",
            source: "./scripts/bucket-mounts",
            target: "/opt/curio-bucket-mounts",
            read_only: "true",
        });
    });

    test("the start script writes the line the self-test reads, in the folder the self-test mounts", () => {
        const script = read(SERVICE_SCRIPT);
        expect(script).toContain(`MOUNTS=${pythonConstant("SERVICE_MOUNTS")}\n`);
        expect(script).toContain(`SELFTEST=${pythonConstant("SELFTEST_FOLDER")}\n`);
        expect(script).toContain(
            `echo "${pythonConstant("SELFTEST_LINE")}" > "$SELFTEST/${pythonConstant("SELFTEST_FILE")}"`,
        );
        expect(volumes(service).map((volume) => volume.target)).not.toContain(pythonConstant("SELFTEST_FOLDER"));
        expect(scalars(service, "tmpfs").map((entry) => entry.split(":")[0])).toContain(
            pythonConstant("SELFTEST_FOLDER"),
        );
    });
});

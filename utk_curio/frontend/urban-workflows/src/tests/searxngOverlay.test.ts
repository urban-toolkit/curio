/**
 * docker-compose.searxng.yml, the overlay a deployment adds for its agents'
 * web search (DEPLOYMENT.md, "Web search"), and scripts/searxng/settings.yml,
 * the settings it binds. The overlay adds the searxng service alone, on the
 * stack's own network with no port published; its image is pinned; it runs as
 * the image's account with no capability on a read-only root; its settings
 * answer in JSON with the limiter off; and its secret key comes from a file
 * that neither git nor the image holds, never from a file in git. The backend
 * suite runs in the CI image, which ships no compose file, so these checks
 * live here. The files are read as text, as bucketMountsOverlay.test.ts reads
 * its overlay.
 */
import * as fs from "fs";
import * as path from "path";
import { REPO_ROOT, read } from "./_support/workflowPaths";
import { block, codeLines, environment, scalars, services, value, volumes } from "./_support/composeFile";

const OVERLAY = "docker-compose.searxng.yml";
const SETTINGS = "scripts/searxng/settings.yml";

const exists = (file: string): boolean => fs.existsSync(path.join(REPO_ROOT, file));

/** The overlay's searxng service. */
function searxng(): string[] {
    expect(exists(OVERLAY)).toBe(true);
    return services(OVERLAY).get("searxng") ?? [];
}

/** The settings' lines, comments left out. */
function settings(): string[] {
    expect(exists(SETTINGS)).toBe(true);
    return codeLines(read(SETTINGS));
}

describe("the web search service's overlay", () => {
    test("it adds the searxng service alone, and nothing else", () => {
        searxng();
        expect([...services(OVERLAY).keys()]).toEqual(["searxng"]);
        expect(codeLines(read(OVERLAY)).filter((line) => /^\S/.test(line))).toEqual(["services:"]);
    });

    test("it publishes no port, takes no fixed name, and joins only the stack's own network", () => {
        const service = searxng();
        expect(service.length).toBeGreaterThan(5);
        for (const key of ["ports", "expose", "network_mode", "networks", "container_name"]) {
            expect([key, service.some((line) => line.startsWith(`    ${key}:`))]).toEqual([key, false]);
        }
    });

    test("its image is a SearXNG release pinned by its digest, on the one image line the deploy pulls it by", () => {
        expect(value(searxng(), "image")).toMatch(
            /^searxng\/searxng:\d{4}\.\d{1,2}\.\d{1,2}-[0-9a-f]{9}@sha256:[0-9a-f]{64}$/,
        );
        expect(read(OVERLAY).split("\n").filter((line) => /^ {4}image: /.test(line))).toHaveLength(1);
    });

    test("it runs as the image's searxng account with no capability, on a read-only root", () => {
        const service = searxng();
        expect(value(service, "user")).toBe('"977:977"');
        expect(scalars(service, "cap_drop")).toEqual(["ALL"]);
        expect(scalars(service, "cap_add")).toEqual([]);
        expect(scalars(service, "security_opt")).toEqual(["no-new-privileges:true"]);
        expect(value(service, "privileged")).toBeUndefined();
        expect(value(service, "read_only")).toBe("true");
    });

    test("what it writes is in memory, and the image's two folders are its account's", () => {
        const tmpfs = scalars(searxng(), "tmpfs");
        expect(tmpfs.map((entry) => entry.split(":")[0]).sort()).toEqual(["/etc/searxng", "/tmp", "/var/cache/searxng"]);
        for (const folder of ["/etc/searxng", "/var/cache/searxng"]) {
            const options = (tmpfs.find((entry) => entry.startsWith(`${folder}:`)) ?? "").split(":")[1]?.split(",") ?? [];
            expect([folder, options]).toEqual([folder, expect.arrayContaining(["uid=977", "gid=977"])]);
        }
    });

    test("it binds this checkout's settings read-only where SearXNG reads them, and nothing else", () => {
        expect(volumes(searxng())).toEqual([
            { type: "bind", source: `./${SETTINGS}`, target: "/etc/searxng/settings.yml", read_only: "true" },
        ]);
    });

    test("its key comes from .secrets/searxng.env, which neither git nor the image holds", () => {
        expect(scalars(searxng(), "env_file")).toEqual(["./.secrets/searxng.env"]);
        expect(read(".gitignore")).toMatch(/^\/\.secrets\/$/m);
        expect(read(".dockerignore")).toMatch(/^\/\.secrets\/$/m);
    });

    test("no file in git sets its key", () => {
        expect(environment(searxng(), "SEARXNG_SECRET")).toBeUndefined();
        expect(read(OVERLAY)).not.toMatch(/SEARXNG_SECRET\s*[:=]/);
        expect(settings().join("\n")).not.toContain("secret_key");
    });

    test("it starts again unless stopped, and is healthy once /healthz answers on its own port", () => {
        const service = searxng();
        expect(value(service, "restart")).toBe("unless-stopped");
        expect(block(service, "healthcheck", 4).join("\n")).toContain('"http://127.0.0.1:8080/healthz"');
    });
});

describe("the web search service's settings", () => {
    test("SearXNG's defaults, answering in JSON, with the limiter off and no public instance's features", () => {
        const lines = settings();
        expect(lines).toContain("use_default_settings: true");
        expect(block(lines, "server", 0)).toEqual(expect.arrayContaining(["  limiter: false", "  public_instance: false"]));
        const formats = /^ {2}formats: \[([^\]]*)\]$/.exec(block(lines, "search", 0).find((line) => line.startsWith("  formats:")) ?? "");
        expect(formats).not.toBeNull();
        expect((formats?.[1] ?? "").split(",").map((format) => format.trim())).toContain("json");
    });
});

/**
 * Both stacks run the web search service (docker-compose.searxng.yml) when the
 * deployed checkout has its overlay, and their Curio searches through it: each
 * job adds the overlay to COMPOSE_FILE after the deploy's and before the site
 * file, and gives Curio's command line --agent-search-url with the service's
 * URL. The service's key is made once, owner-only, in the checkout's
 * .secrets/searxng.env, before the first docker compose command reads it, and
 * no line prints it; its image is pulled while the old stack still serves.
 * Once the stack is up, each job fails unless Curio has the URL and, from
 * Curio's container, the URL answers with JSON that holds a results list
 * (scripts/searxng/check.py); no results only warns. The Full stack build's
 * bucket-mounts job asks the same URL through the same check. The files are
 * read as text, as deployBucketMounts.test.ts reads them.
 */
import * as fs from "fs";
import * as path from "path";
import { block, scalars, services } from "./_support/composeFile";
import { REPO_ROOT, read } from "./_support/workflowPaths";

const WORKFLOW = ".github/workflows/deploy.yml";
const BUILD = ".github/workflows/docker-compose.yml";
const OVERLAY = "docker-compose.searxng.yml";
const CHECK = "scripts/searxng/check.py";
const KEY_FILE = ".secrets/searxng.env";
/** The URL each stack gives Curio's --agent-search-url. */
const SEARCH_URL = "http://searxng:8080/search?q={q}&format=json";

const text = read(WORKFLOW);
const jobs = text.split(/^ {2}deploy-(?:dev|stable):$/m).slice(1);
/** Each stack's name, its Compose project and its job's text. */
const STACKS: Array<[string, string, string]> = [
    ["dev", "curio-dev", jobs[0] ?? ""],
    ["stable", "curio", jobs[1] ?? ""],
];

const exists = (file: string): boolean => fs.existsSync(path.join(REPO_ROOT, file));
const escape = (literal: string): string => literal.replace(/[.*+?^${}()|[\]\\/]/g, "\\$&");

/** Where `needle` is in `haystack`, which must hold it once. */
function once(haystack: string, needle: string): number {
    const first = haystack.indexOf(needle);
    expect([needle, first > -1]).toEqual([needle, true]);
    expect([needle, haystack.indexOf(needle, first + 1)]).toEqual([needle, -1]);
    return first;
}

/** The job's `if [ -n "$search_args" ]` block that starts the checks, once the stack is up. */
function checks(job: string): string {
    const match = /^( +)if \[ -n "\$search_args" \]; then\n\1 {2}echo "=== web search ==="\n[\s\S]*?\n\1fi$/m.exec(job);
    expect(match).not.toBeNull();
    return match?.[0] ?? "";
}

describe("The deploy's web search", () => {
    test("the URL Curio gets is the overlay's service, on the port its healthcheck asks, answering in JSON", () => {
        expect(exists(OVERLAY)).toBe(true);
        const overlay = services(OVERLAY);
        expect([...overlay.keys()]).toEqual(["searxng"]);
        const url = new URL(SEARCH_URL.replace("{q}", "query"));
        expect([url.protocol, url.hostname, url.port, url.pathname]).toEqual(["http:", "searxng", "8080", "/search"]);
        expect(url.searchParams.get("q")).toBe("query");
        expect(url.searchParams.get("format")).toBe("json");
        expect(block(overlay.get("searxng") ?? [], "healthcheck", 4).join("\n")).toContain(`:${url.port}/healthz"`);
        expect(read("utk_curio/main.py")).toMatch(/"--agent-search-url", default=None/);
    });

    test("each stack turns web search on only when its checkout has the overlay", () => {
        // The two jobs are dev's and stable's.
        expect(jobs).toHaveLength(2);
        expect(STACKS[0][2]).toContain("\n          cd /srv/curio-dev\n");
        expect(STACKS[1][2]).toContain("\n          cd /srv/curio\n");
        const args = `search_args=", \\"--agent-search-url\\", \\"$search_url\\""`;
        expect(text.split(args)).toHaveLength(3);
        for (const [, , job] of STACKS) {
            expect(job.match(/^ +search_url=.*$/gm)).toEqual([
                expect.stringMatching(new RegExp(`^ +search_url='${escape(SEARCH_URL)}'$`)),
            ]);
            const unset = once(job, 'search_args=""');
            const guard = once(job, "if [ -f docker-compose.searxng.yml ]; then");
            expect(unset).toBeLessThan(guard);
            expect(guard).toBeLessThan(once(job, args));
        }
    });

    test("each stack's key is made once, owner-only, before any docker compose command reads it, and nothing prints it", () => {
        expect(exists(OVERLAY)).toBe(true);
        expect(scalars(services(OVERLAY).get("searxng") ?? [], "env_file")).toEqual([`./${KEY_FILE}`]);
        const make = [
            `if [ ! -s ${KEY_FILE} ]; then`,
            "(",
            "umask 077",
            "mkdir -p .secrets",
            `printf 'SEARXNG_SECRET=%s\\n' "$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \\n')" > ${KEY_FILE}.new`,
            `mv ${KEY_FILE}.new ${KEY_FILE}`,
            ")",
            "fi",
        ];
        for (const [, project, job] of STACKS) {
            const lines = job.split("\n").map((line) => line.trim());
            const first = lines.indexOf(make[0]);
            expect(first).toBeGreaterThan(-1);
            expect(lines.slice(first, first + make.length)).toEqual(make);
            const made = once(job, make[0]);
            expect(once(job, "if [ -f docker-compose.searxng.yml ]; then")).toBeLessThan(made);
            // Compose reads the overlay's env_file for every command, the build and `down` among them.
            expect(made).toBeLessThan(once(job, `docker compose -p ${project} build --no-cache`));
            expect(made).toBeLessThan(once(job, `docker compose -p ${project} down`));
        }
        // No line reads the file back or prints the key, and nothing prints
        // the merged configuration, which holds it.
        expect(text).not.toMatch(/\b(cat|less|more|head|tail|grep|sed|awk)\s+[^|\n]*\.secrets\/searxng\.env/);
        expect(text).not.toMatch(/<\s*\S*\.secrets\/searxng\.env/);
        expect(text).not.toMatch(/\$\{?SEARXNG_SECRET/);
        expect(text).not.toMatch(/docker compose[^\n]* config\b/);
    });

    test("each stack pulls the service's image while the old stack still serves, and fails there when it cannot", () => {
        expect(exists(OVERLAY)).toBe(true);
        expect(read(OVERLAY).split("\n").filter((line) => /^ {4}image: /.test(line))).toHaveLength(1);
        for (const [, project, job] of STACKS) {
            const pull = once(
                job,
                'if ! docker image inspect "$search_image" > /dev/null 2>&1 && ! docker pull -q "$search_image" > /dev/null < /dev/null; then\n',
            );
            expect(once(job, `search_image="$(sed -n 's/^    image: //p' ${OVERLAY})"`)).toBeLessThan(pull);
            expect(pull).toBeLessThan(once(job, `docker compose -p ${project} down`));
            const after = job.slice(pull).split("\n").slice(1, 3).map((line) => line.trim());
            expect(after).toEqual([`echo "::error::could not pull $search_image, the web search service's image"`, "exit 1"]);
        }
    });

    test("each stack's command line passes the URL, after setting it", () => {
        for (const [, , job] of STACKS) {
            const command = job.search(/printf ' {4}command: \[[^\n]* "\$llm_args" "\$search_args" [^\n]*>> docker-compose\.site\.yml\n/);
            expect(command).toBeGreaterThan(-1);
            expect(job.indexOf('search_args=", \\"--agent-search-url\\"')).toBeLessThan(command);
        }
    });

    test("COMPOSE_FILE takes the overlay after the deploy's and before the site file, only when the stack runs it", () => {
        for (const [, project, job] of STACKS) {
            expect(job).toMatch(
                /^( +)if \[ -n "\$search_args" \]; then\n\1 {2}export COMPOSE_FILE=\$COMPOSE_FILE:docker-compose\.searxng\.yml\n\1fi$/m,
            );
            const added = once(job, "export COMPOSE_FILE=$COMPOSE_FILE:docker-compose.searxng.yml");
            expect(once(job, "export COMPOSE_FILE=docker-compose.yml:docker-compose.deploy.yml")).toBeLessThan(added);
            expect(added).toBeLessThan(once(job, "export COMPOSE_FILE=$COMPOSE_FILE:docker-compose.site.yml"));
            expect(added).toBeLessThan(once(job, `docker compose -p ${project} build --no-cache`));
        }
    });

    test("once the stack is up, each job fails unless Curio has the URL and it answers from Curio's container with JSON", () => {
        expect(exists(CHECK)).toBe(true);
        const script = read(CHECK);
        expect(script).toContain('line = f"results: {len(results)}"');
        expect(script).toContain("return 0 if ok else 1");
        // What /monitor's searchToolConfigured reads: the variable --agent-search-url sets.
        expect(read("utk_curio/backend/app/monitor/routes.py")).toContain(
            '"searchToolConfigured": bool(os.environ.get("CURIO_SEARCH_URL", "").strip()),',
        );
        for (const [, project, job] of STACKS) {
            const wait = checks(job);
            const at = job.indexOf(wait);
            expect(once(job, `docker compose -p ${project} up -d --force-recreate --remove-orphans`)).toBeLessThan(at);
            expect(once(job, 'echo "=== waiting for health ==="')).toBeLessThan(at);
            expect(at).toBeLessThan(once(job, 'echo "=== docker ps (post-deploy) ==="'));
            expect(wait).toContain(`docker compose -p ${project} exec -T curio \\\n`);
            expect(wait).toContain('["deployment"]["searchToolConfigured"]');
            expect(wait).toContain(`python ${CHECK} "$search_url" 2>&1 < /dev/null)" \\\n`);
            expect(wait).toContain('&& [ "$search_flag" = "True" ]; then\n');
            expect(wait).toMatch(/"results: 0"\*\)\n +echo "::warning::[^\n]*"\n/);
            expect(wait).toMatch(/if \[ "\$SECONDS" -ge "\$deadline" \]; then\n +echo "::error::[^\n]*"\n/);
            expect(wait).toContain(`docker compose -p ${project} logs --no-color --tail=100 searxng || true\n`);
            expect(wait.match(/^ +exit 1$/gm)).toHaveLength(1);
            expect(wait).toMatch(/^ +sleep 5\n +done$/m);
        }
    });

    test("every docker compose exec of the checks reads /dev/null, so none takes the rest of the script", () => {
        for (const [, , job] of STACKS) {
            const execs = checks(job)
                .replace(/\\\n\s*/g, " ")
                .split("\n")
                .filter((line) => /docker compose [^\n]* exec /.test(line));
            expect(execs).toHaveLength(2);
            for (const exec of execs) {
                expect(exec).toContain("< /dev/null");
            }
        }
    });

    test("the Full stack build asks the same URL through the same check, from a container on the service's network", () => {
        const build = read(BUILD);
        const job = build.slice(build.search(/^ {2}bucket-mounts:$/m), build.search(/^ {2}test-desktop-stress:$/m));
        expect(job).toMatch(/^ {10}COMPOSE_FILE: docker-compose\.searxng\.yml$/m);
        expect(job).toMatch(/^ {10}COMPOSE_PROJECT_NAME: curio-ci-searxng$/m);
        expect(job).toContain("docker compose up -d --wait --wait-timeout 120");
        expect(job).toContain(
            `docker run --rm --network curio-ci-searxng_default -v "$PWD/scripts/searxng:/check:ro" python:3.12-alpine`,
        );
        expect(job).toContain(`python /check/check.py '${SEARCH_URL}'`);
        expect(job).toContain("docker compose -p curio-ci-searxng -f docker-compose.searxng.yml down -v --remove-orphans || true");
    });
});

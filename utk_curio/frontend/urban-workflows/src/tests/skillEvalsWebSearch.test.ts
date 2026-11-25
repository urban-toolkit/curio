/**
 * The Skill evaluations workflow's agents search the web through the service
 * dev and stable search through (docker-compose.searxng.yml), not Curio's
 * default. Once main's image is pulled, and only when the run measures
 * something, the job makes the service's key as the deploy makes it
 * (owner-only, random, printed nowhere), starts the service in the job's own
 * compose project, and asks the URL dev and stable give Curio's
 * --agent-search-url from a container of that image on the service's network
 * (scripts/searxng/check.py, the deploy's own check): no JSON answer ends the
 * job there, with the service's last lines, and no results only warns. The
 * evaluations' container joins the same network and gets the URL by name, as
 * CURIO_SEARCH_URL, which every worker's web.search reads, with the words the
 * report names that search with. The service stops at the job's end whatever
 * happened, and the next job's first step removes what a cancelled job left of
 * it, its network among it, as the Full stack build's first step does. The
 * files are read as text, as deployWebSearch.test.ts reads them.
 */
import { services } from "./_support/composeFile";
import { read } from "./_support/workflowPaths";

const WORKFLOW = ".github/workflows/skill-evals.yml";
const DEPLOY = ".github/workflows/deploy.yml";
const BUILD = ".github/workflows/docker-compose.yml";
const OVERLAY = "docker/docker-compose.searxng.yml";
const CHECK = "scripts/searxng/check.py";
const KEY_FILE = ".secrets/searxng.env";
/** The compose commands of the job's web search: its own project, the overlay alone. */
const SEARCH = `docker compose -p "$PROJECT" -f ${OVERLAY}`;
const UP = `${SEARCH} up -d --wait --wait-timeout 120`;
const DOWN = `${SEARCH} down -v --remove-orphans`;
/** The service's network, which compose names after the project. */
const NETWORK = '--network "${PROJECT}_default"';
const LABEL = '--label "com.docker.compose.project=$PROJECT"';
/** The step gate of every step that needs a scope. */
const MEASURES = "steps.scope.outputs.skill_evals != ''";
/** How the deploy makes each stack's key, line by line. */
const MAKE = [
    `if [ ! -s ${KEY_FILE} ]; then`,
    "(",
    "umask 077",
    "mkdir -p .secrets",
    `printf 'SEARXNG_SECRET=%s\\n' "$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \\n')" > ${KEY_FILE}.new`,
    `mv ${KEY_FILE}.new ${KEY_FILE}`,
    ")",
    "fi",
];

const text = read(WORKFLOW);

/** The URL dev and stable give Curio's --agent-search-url: deploy.yml's search_url, the same in every job. */
function deployedSearchUrl(): string {
    const urls = [...read(DEPLOY).matchAll(/^ +search_url='([^']+)'$/gm)].map((match) => match[1]);
    expect(urls.length).toBeGreaterThan(0);
    expect(new Set(urls).size).toBe(1);
    return urls[0];
}

/** The job's own `env:` value of *name*, unquoted. */
function jobEnv(name: string): string | undefined {
    const lines = text.split("\n");
    const start = lines.indexOf("    env:");
    const end = lines.indexOf("    steps:");
    expect([start > -1, end > start]).toEqual([true, true]);
    for (const line of lines.slice(start + 1, end)) {
        const match = new RegExp(`^ {6}${name}:\\s*(.+)$`).exec(line);
        if (match) return match[1].trim().replace(/^(["'])(.*)\1$/, "$2");
    }
    return undefined;
}

/** The job's steps in order, each its lines from its `- ` line to the next step's, whole-line comments left out. */
function steps(): string[] {
    const lines = text.split("\n");
    const start = lines.indexOf("    steps:");
    expect(start).toBeGreaterThan(-1);
    const found: string[][] = [];
    for (const line of lines.slice(start + 1)) {
        if (/^\s*#/.test(line)) continue;
        if (/^ {6}- /.test(line)) found.push([line]);
        else found[found.length - 1]?.push(line);
    }
    return found.map((step) => step.join("\n"));
}

/** The one step that holds *needle*, by its place among the steps. */
function stepWith(needle: string): number {
    const all = steps();
    const places = all.flatMap((step, place) => (step.includes(needle) ? [place] : []));
    expect([needle, places.length]).toEqual([needle, 1]);
    return places[0];
}

/** A step's `if:`. */
const gate = (step: string): string | undefined => /^ {8}if: (.+)$/m.exec(step)?.[1].trim();

/** A step's own `env:` value of *name*. */
function stepEnv(step: string, name: string): string | undefined {
    const lines = step.split("\n");
    const start = lines.indexOf("        env:");
    if (start < 0) return undefined;
    for (const line of lines.slice(start + 1)) {
        if (line.trim() !== "" && line.length - line.trimStart().length <= 8) break;
        const match = new RegExp(`^ {10}${name}:\\s*(.+)$`).exec(line);
        if (match) return match[1].trim();
    }
    return undefined;
}

/** A step's shell lines with each `\` continuation joined to its line. */
const joined = (step: string): string[] => step.replace(/\\\n\s*/g, " ").split("\n");

/** The one command line of *step* that holds *needle*, continuations joined. */
function command(step: string, needle: string): string {
    const found = joined(step).filter((line) => line.includes(needle));
    expect([needle, found.length]).toEqual([needle, 1]);
    return found[0];
}

/** The lines of the `for project in $projects; do` loop of a first step, trimmed, to its `done`. */
function removalLoop(step: string): string[] {
    const lines = step.split("\n").map((line) => line.trim());
    const start = lines.indexOf("for project in $projects; do");
    expect(start).toBeGreaterThan(-1);
    return lines.slice(start, lines.indexOf("done", start) + 1);
}

describe("The skill evaluations' web search", () => {
    test("the job searches at the URL dev and stable give Curio, the overlay's service", () => {
        const url = deployedSearchUrl();
        expect(jobEnv("CURIO_SEARCH_URL")).toBe(url);
        expect([...services(OVERLAY).keys()]).toEqual(["searxng"]);
        expect(new URL(url.replace("{q}", "query")).hostname).toBe("searxng");
        // Its project is one the first step of the next job on the runner finds.
        expect(jobEnv("PROJECT")).toMatch(/^curio-ci-/);
    });

    test("the service starts in the job's own project once main's image is here, before any evaluation", () => {
        const all = steps();
        const pull = stepWith('docker tag "$image" "$PROJECT-curio"');
        const search = stepWith(UP);
        const evaluate = stepWith("python scripts/ci_skill_evals.py run");
        expect(pull).toBeLessThan(search);
        expect(search).toBeLessThan(evaluate);
        expect(gate(all[search])).toBe(MEASURES);
        expect(all[search]).toMatch(/^ {8}id: search$/m);
        expect(all[search]).toMatch(/^ {8}shell: bash$/m);
        // Every compose command of it names the project and the overlay alone.
        const composes = joined(all[search]).filter((line) => /docker compose /.test(line));
        expect(composes.length).toBeGreaterThan(1);
        for (const line of composes) expect(line).toContain(SEARCH);
        // Nothing gives the whole job a compose file, which stop-stack's own `down` would read.
        expect(jobEnv("COMPOSE_FILE")).toBeUndefined();
    });

    test("its key is made as the deploy makes it, owner-only, before any compose command reads it, and nothing prints it", () => {
        const deployLines = read(DEPLOY).split("\n").map((line) => line.trim());
        const made = deployLines.indexOf(MAKE[0]);
        expect(deployLines.slice(made, made + MAKE.length)).toEqual(MAKE);
        const step = steps()[stepWith(UP)];
        const lines = step.split("\n").map((line) => line.trim());
        const first = lines.indexOf(MAKE[0]);
        expect(first).toBeGreaterThan(-1);
        expect(lines.slice(first, first + MAKE.length)).toEqual(MAKE);
        expect(step.indexOf(MAKE[0])).toBeLessThan(step.indexOf("docker compose"));
        // No line reads the file back or prints the key, nothing prints the
        // merged configuration, which holds it, and no shell traces its lines.
        expect(text).not.toMatch(/\b(cat|less|more|head|tail|grep|sed|awk)\s+[^|\n]*\.secrets\/searxng\.env/);
        expect(text).not.toMatch(/<\s*\S*\.secrets\/searxng\.env/);
        expect(text).not.toMatch(/\$\{?SEARXNG_SECRET/);
        expect(text).not.toMatch(/docker compose[^\n]* config\b/);
        expect(text).not.toMatch(/\bset -[a-z]*x|\bxtrace\b|\bbash -[a-z]*x/);
    });

    test("from a container on the service's network the URL answers with JSON before any evaluation, or the job ends there", () => {
        const step = steps()[stepWith(UP)];
        const check = command(step, `python ${CHECK} "$CURIO_SEARCH_URL"`);
        expect(check).toContain("docker run --rm ");
        expect(check).toContain(NETWORK);
        expect(check).toContain(LABEL);
        // The image the evaluations run in, with this checkout's check.
        expect(check).toContain('-v "$PWD:/app:ro" -w /app "$PROJECT-curio"');
        expect(step.indexOf(UP)).toBeLessThan(step.indexOf(`python ${CHECK}`));
        // The service's last lines, then the one way out.
        expect(step).toContain(`${SEARCH} logs --no-color --tail=100 searxng || true\n`);
        expect(step.indexOf(`python ${CHECK}`)).toBeLessThan(step.indexOf(`${SEARCH} logs`));
        expect(step.match(/^ +exit 1$/gm)).toHaveLength(1);
        expect(step).toMatch(/echo "::error::[^\n]*"\n +[^\n]* logs --no-color --tail=100 searxng \|\| true\n +exit 1\n/);
        // No results anywhere in what the check printed only warns, as on the deploy.
        expect(step).toMatch(/^ +\*"results: 0,"\*\)\n +echo "::warning::[^\n]*"\n/m);
    });

    test("the evaluations' container joins the service's network and gets the URL and its name by name", () => {
        const all = steps();
        const evaluate = all[stepWith("python scripts/ci_skill_evals.py run")];
        const run = command(evaluate, '"$PROJECT-curio"');
        expect(run).toContain("docker run --rm --init ");
        expect(run).toContain(LABEL);
        expect(run).toContain(NETWORK);
        expect(run).toMatch(/ -e CURIO_SEARCH_URL /);
        expect(run).toMatch(/ -e CURIO_EVAL_SEARCH /);
        expect(evaluate).not.toContain("CURIO_SEARCH_URL=");
        // What the report names the search: the overlay's service and the image it pins.
        expect(stepEnv(evaluate, "CURIO_EVAL_SEARCH")).toBe("${{ steps.search.outputs.search }}");
        const search = all[stepWith(UP)];
        expect(search).toContain(`image="$(sed -n 's/^    image: //p' ${OVERLAY})"`);
        expect(search).toContain('echo "search=SearXNG ${image%%@*}" >> "$GITHUB_OUTPUT"');
        expect(read(OVERLAY).split("\n").filter((line) => /^ {4}image: searxng\/searxng:[^@\s]+@sha256:/.test(line))).toHaveLength(1);
    });

    test("the service stops at the job's end whatever happened, before the stack's teardown", () => {
        const all = steps();
        const evaluate = stepWith("python scripts/ci_skill_evals.py run");
        const stop = stepWith(DOWN);
        const teardown = stepWith("uses: ./.github/actions/stop-stack");
        expect(gate(all[stop])).toBe("always()");
        expect(evaluate).toBeLessThan(stop);
        expect(stop).toBeLessThan(teardown);
        expect(teardown).toBe(all.length - 1);
    });

    test("the next job's first step removes what a cancelled job left of the service, its network among it", () => {
        const all = steps();
        expect(stepWith("uses: actions/checkout")).toBe(1);
        const loop = removalLoop(all[0]);
        expect(loop).toContain('docker network ls -q --filter "$label" | xargs -r docker network rm');
        // The Full stack build's first step removes a stack the same way.
        const build = read(BUILD);
        const reclaim = build.slice(build.indexOf("- &reclaim"), build.indexOf("- name: ", build.indexOf("- &reclaim") + 1));
        expect(loop).toEqual(removalLoop(reclaim));
        expect(all[0]).toContain(`grep '^curio-ci'`);
    });
});

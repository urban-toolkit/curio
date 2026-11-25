/**
 * A change to anything the deployed image copies, or to a file the deploy
 * builds the image or starts a stack with, redeploys curio-dev, once.
 *
 * .github/workflows/bump-version.yml runs on a push to main that changes a
 * file its `paths` filter matches, bumps the version and dispatches
 * .github/workflows/deploy.yml for curio-dev, which builds the image from the
 * Dockerfile and starts the stack with the compose files its COMPOSE_FILE
 * names. A folder the image copies, or one of those files, that the filter
 * misses can change on main while curio-dev keeps serving the old one. What
 * the image copies is read from the Dockerfile, as fullStackBuildPaths.test.ts
 * reads it.
 *
 * Each deploy job finds those compose files in docker/, or at the root of a
 * ref from before docker/ held them, and writes its site file beside them.
 */
import { copiedIntoTheImage, fileIn, pathsFilters, read, startsARun } from "./_support/workflowPaths";

const BUMP = ".github/workflows/bump-version.yml";
const DEPLOY = ".github/workflows/deploy.yml";

/**
 * What the image carries only for CI's packaging tests, as the Dockerfile's
 * comment above their COPY says: the deployed app never reads them, so a
 * change to them alone needs no deploy.
 */
const FOR_CI_ONLY = ["pyproject.toml", "MANIFEST.in", "setup.py"];

/** How each deploy job finds its compose files, and names its site file beside them. */
const COMPOSE_FOLDER = [
    "compose_dir=docker",
    "if [ ! -f docker/docker-compose.yml ]; then",
    "compose_dir=.",
    "fi",
    "site=$compose_dir/docker-compose.site.yml",
];

/** Each deploy job's text: dev's, then stable's. */
function deployJobs(): string[] {
    return read(DEPLOY).split(/^ {2}deploy-(?:dev|stable):$/m).slice(1);
}

/**
 * The compose files deploy.yml starts a stack with, from its COMPOSE_FILE
 * exports, as this checkout holds them: in docker/. The site file, which each
 * job writes, is left out.
 */
function deployComposeFiles(): string[] {
    const files = new Set<string>();
    for (const [, list] of read(DEPLOY).matchAll(/^ *export COMPOSE_FILE=(\S+)$/gm)) {
        for (const entry of list.split(":")) {
            if (entry === "$COMPOSE_FILE" || entry === "$site") continue;
            files.add(entry.replace(/^\$compose_dir\//, "docker/"));
        }
    }
    return [...files];
}

/** The events of a workflow's top-level `on:` block. */
function events(workflow: string): string[] {
    const block = /^on:[ \t]*\n((?:[ \t]+.*\n|[ \t]*\n)*)/m.exec(read(workflow));
    if (!block) throw new Error(`${workflow} has no top-level on: block`);
    return [...block[1].matchAll(/^ {2}([A-Za-z_]+):/gm)].map((match) => match[1]);
}

describe(`the paths filter of ${BUMP}`, () => {
    const patterns = pathsFilters(BUMP).get("push") ?? [];

    test("push has one", () => {
        // Read as text: next to no paths means the reading broke, not that
        // nothing deploys.
        expect(patterns).toContain("utk_curio/**");
        expect(patterns.length).toBeGreaterThan(10);
    });

    test("a change to anything the deployed image copies redeploys curio-dev", () => {
        const copied = copiedIntoTheImage().filter((source) => !FOR_CI_ONLY.includes(source));
        expect(copied.length).toBeGreaterThan(10);
        expect(copied.filter((source) => !startsARun(fileIn(source), patterns))).toEqual([]);
    });

    test("a change to the image's Dockerfile or ignore file, or to a compose file the deploy starts a stack with, redeploys curio-dev", () => {
        const composeFiles = deployComposeFiles();
        // The base and the deploy overlay, and the two services' overlays.
        expect(composeFiles).toEqual(
            expect.arrayContaining([
                "docker/docker-compose.yml",
                "docker/docker-compose.deploy.yml",
                "docker/docker-compose.searxng.yml",
                "docker/docker-compose.bucket-mounts.yml",
            ]),
        );
        const files = [...composeFiles, "docker/Dockerfile", "docker/Dockerfile.dockerignore"];
        expect(files.filter((file) => !startsARun(file, patterns))).toEqual([]);
    });

    test("the bump dispatches the dev deploy", () => {
        const bump = read(BUMP);
        expect(bump).toContain("actions/workflows/deploy.yml/dispatches");
        expect(bump).toContain(`'{"ref":"main","inputs":{"ref":"main","target":"dev"}}'`);
    });
});

describe(DEPLOY, () => {
    test("deploys only when dispatched, so a merge deploys curio-dev once", () => {
        // A push trigger beside Bump version's dispatch deployed every merge
        // twice: the merge commit, then a minute later the bump commit.
        expect(events(DEPLOY)).toEqual(["workflow_dispatch"]);
    });

    test("there is one job for each stack", () => {
        expect(deployJobs()).toHaveLength(2);
    });

    test.each([0, 1])("job %s finds its compose files once its checkout is in place", (index) => {
        const lines = (deployJobs()[index] ?? "").split("\n").map((line) => line.trim());
        const first = lines.indexOf(COMPOSE_FOLDER[0]);
        expect(first).toBeGreaterThan(-1);
        expect(lines.slice(first, first + COMPOSE_FOLDER.length)).toEqual(COMPOSE_FOLDER);
        expect(lines.filter((line) => line === COMPOSE_FOLDER[0])).toHaveLength(1);
        const checkout = lines.findIndex((line) => line.startsWith('git checkout --detach "origin/$ref"'));
        expect(checkout).toBeGreaterThan(-1);
        expect(checkout).toBeLessThan(first);
    });

    test.each([0, 1])("job %s names each compose file and its site file in that folder, after finding it", (index) => {
        const lines = (deployJobs()[index] ?? "").split("\n").map((line) => line.trim());
        const found = lines.indexOf(COMPOSE_FOLDER[COMPOSE_FOLDER.length - 1]);
        // The script's lines, but its comments and the messages it prints.
        const naming = lines
            .map((line, at): [number, string] => [at, line])
            .filter(([, line]) => /docker-compose\.[a-z.-]*yml|\$site\b/.test(line))
            .filter(([, line]) => !line.startsWith("#") && !line.startsWith("echo ") && !COMPOSE_FOLDER.includes(line));
        expect(naming.length).toBeGreaterThan(10);
        for (const [at, line] of naming) {
            expect([line, at > found]).toEqual([line, true]);
            const bare = line.replace(/\$compose_dir\/docker-compose\.[a-z.-]*yml/g, "");
            expect([line, /docker-compose\.[a-z.-]*yml/.test(bare)]).toEqual([line, false]);
        }
    });
});

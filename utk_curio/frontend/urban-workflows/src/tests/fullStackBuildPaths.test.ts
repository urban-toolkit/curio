/**
 * A change to anything the Full stack build builds or reads starts it.
 *
 * .github/workflows/docker-compose.yml runs on a push or a pull request only
 * when a changed file matches the event's `paths` filter. A file the build
 * depends on that the filter misses can change with no build at all, and the
 * next unrelated change is the one whose build fails. What the image copies is
 * read from the Dockerfile; the files the jobs read from the checkout besides
 * are listed here with their readers. The backend suite runs in the CI image,
 * which ships neither the workflow nor the Dockerfile, so this check lives here.
 */
import * as fs from "fs";
import * as path from "path";

const REPO_ROOT = path.join(__dirname, "..", "..", "..", "..", "..");
const WORKFLOW = ".github/workflows/docker-compose.yml";
const EVENTS = ["push", "pull_request"];

/** Files the jobs read from the checkout that the image does not copy, and their readers. */
const READ_FROM_THE_CHECKOUT: Array<[string, string]> = [
    [".nvmrc", "setup-node in jest and preview-runner, and scripts/check_node_pins.py"],
    [".node-version", "scripts/check_node_pins.py"],
    ["docker-compose.deploy.yml", "test-gpu's check of the production deploy configuration"],
];

function read(file: string): string {
    return fs.readFileSync(path.join(REPO_ROOT, file), "utf-8");
}

/** Each event's `paths` list, from the workflow's top-level `on:` block. */
function pathsFilters(): Map<string, string[]> {
    const lines = read(WORKFLOW).split("\n");
    const start = lines.findIndex((line) => /^on:\s*$/.test(line));
    if (start < 0) throw new Error(`${WORKFLOW} has no top-level on: block`);
    const filters = new Map<string, string[]>();
    let event = "";
    let list: string[] | null = null;
    for (const line of lines.slice(start + 1)) {
        if (/^\s*(#.*)?$/.test(line)) continue;
        if (/^\S/.test(line)) break;
        const indent = line.length - line.trimStart().length;
        if (list) {
            const item = /^\s+-\s+(?:'([^']*)'|"([^"]*)"|([^\s'"#]+))\s*(?:#.*)?$/.exec(line);
            if (item) {
                list.push(item[1] ?? item[2] ?? item[3]);
                continue;
            }
            // Deeper than `paths:` and not an item: a line this reading does
            // not understand, which must not end the list unnoticed.
            if (indent > 4) throw new Error(`${WORKFLOW}: cannot read the filter line ${JSON.stringify(line)}`);
            list = null;
        }
        const key = /^\s*([A-Za-z_-]+):/.exec(line);
        if (!key) continue;
        if (indent === 2) {
            event = key[1];
        } else if (indent === 4 && key[1] === "paths") {
            list = [];
            filters.set(event, list);
        }
    }
    return filters;
}

/** A `paths` pattern as GitHub matches it: `**` crosses folders, `*` does not. */
function patternRegExp(pattern: string): RegExp {
    if (/[?+[\]!]/.test(pattern)) throw new Error(`${pattern}: this test reads only * and ** in a pattern`);
    const escape = (text: string) => text.replace(/[.^${}()|\\]/g, "\\$&");
    const source = pattern
        .split("**")
        .map((part) => part.split("*").map(escape).join("[^/]*"))
        .join(".*");
    return new RegExp(`^${source}$`);
}

function startsABuild(file: string, patterns: string[]): boolean {
    return patterns.some((pattern) => patternRegExp(pattern).test(file));
}

/** The sources of every COPY and ADD in the Dockerfile that copies from the build context. */
function copiedIntoTheImage(): string[] {
    const instructions = read("Dockerfile").replace(/\\\r?\n/g, " ").split("\n");
    const sources: string[] = [];
    for (const line of instructions) {
        const match = /^\s*(?:COPY|ADD)\s+(.+)$/i.exec(line);
        if (!match) continue;
        const words = match[1].trim().split(/\s+/);
        // --from copies from another stage or image, not from the checkout.
        if (words.some((word) => word.startsWith("--from="))) continue;
        const rest = words.filter((word) => !word.startsWith("--")).join(" ");
        const args: string[] = rest.startsWith("[") ? JSON.parse(rest) : rest.split(" ");
        sources.push(...args.slice(0, -1));
    }
    return sources;
}

/** A file whose change is a change to *source*: itself, or one two folders inside it. */
function fileIn(source: string): string {
    if (/[*?[]/.test(source)) throw new Error(`${source}: this test reads no wildcard in a COPY source`);
    const relative = path.posix.normalize(source).replace(/\/$/, "");
    const folder = fs.statSync(path.join(REPO_ROOT, relative)).isDirectory();
    return folder ? path.posix.join(relative, "a", "b") : relative;
}

describe(`the paths filters of ${WORKFLOW}`, () => {
    const filters = pathsFilters();
    const patterns = (event: string) => filters.get(event) ?? [];

    test("push and pull_request each have one, and the same one", () => {
        for (const event of EVENTS) {
            // Read as text: next to no paths means the reading broke, not
            // that the build starts on nothing.
            expect(patterns(event)).toContain("utk_curio/**");
            expect(patterns(event).length).toBeGreaterThan(10);
        }
        expect(patterns("pull_request")).toEqual(patterns("push"));
    });

    test.each(EVENTS)("on %s, a change to anything the image copies starts a build", (event) => {
        const copied = copiedIntoTheImage();
        expect(copied.length).toBeGreaterThan(10);
        expect(copied.filter((source) => !startsABuild(fileIn(source), patterns(event)))).toEqual([]);
    });

    const readers = EVENTS.flatMap((event) =>
        READ_FROM_THE_CHECKOUT.map(([file, reader]): [string, string, string] => [event, file, reader]),
    );
    test.each(readers)("on %s, a change to %s starts a build (read by %s)", (event, file) => {
        expect(startsABuild(file, patterns(event))).toBe(true);
    });

    // launcherFlagsInGuides.test.ts reads every guide, solveStopReasonsDocs.test.ts
    // docs/ARCHITECTURE.md, and the e2e examples checks docs/README.md.
    test.each(EVENTS)("on %s, a change to a guide under docs/ starts a build", (event) => {
        const guides = fs
            .readdirSync(path.join(REPO_ROOT, "docs"))
            .filter((name) => name.endsWith(".md"))
            .map((name) => `docs/${name}`);
        expect(guides.length).toBeGreaterThan(5);
        expect(guides.filter((file) => !startsABuild(file, patterns(event)))).toEqual([]);
    });
});

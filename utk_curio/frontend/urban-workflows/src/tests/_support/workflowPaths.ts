/**
 * What a workflow's `paths` filter starts a run on, and what the Docker image
 * copies, read from the checkout for the tests that hold one to the other
 * (fullStackBuildPaths.test.ts, deployPaths.test.ts).
 */
import * as fs from "fs";
import * as path from "path";

export const REPO_ROOT = path.join(__dirname, "..", "..", "..", "..", "..", "..");

export function read(file: string): string {
    return fs.readFileSync(path.join(REPO_ROOT, file), "utf-8");
}

/** Each event's `paths` list, from the workflow's top-level `on:` block. */
export function pathsFilters(workflow: string): Map<string, string[]> {
    const lines = read(workflow).split("\n");
    const start = lines.findIndex((line) => /^on:\s*$/.test(line));
    if (start < 0) throw new Error(`${workflow} has no top-level on: block`);
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
            if (indent > 4) throw new Error(`${workflow}: cannot read the filter line ${JSON.stringify(line)}`);
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

export function startsARun(file: string, patterns: string[]): boolean {
    return patterns.some((pattern) => patternRegExp(pattern).test(file));
}

/** The sources of every COPY and ADD in the Dockerfile that copies from the build context. */
export function copiedIntoTheImage(): string[] {
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
export function fileIn(source: string): string {
    if (/[*?[]/.test(source)) throw new Error(`${source}: this test reads no wildcard in a COPY source`);
    const relative = path.posix.normalize(source).replace(/\/$/, "");
    const folder = fs.statSync(path.join(REPO_ROOT, relative)).isDirectory();
    return folder ? path.posix.join(relative, "a", "b") : relative;
}

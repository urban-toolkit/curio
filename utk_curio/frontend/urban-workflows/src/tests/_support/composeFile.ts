/**
 * A compose file read as text, for the tests that hold the overlays and the
 * Deploy workflow's site file to each other (bucketMountsOverlay.test.ts,
 * deployBucketMounts.test.ts): the backend suite runs in the CI image, which
 * ships no compose file, and the frontend has no YAML parser.
 */
import { read } from "./workflowPaths";

/** A file's lines, comments left out: whole-line ones and trailing ` # ...`. */
export function codeLines(text: string): string[] {
    return text
        .split("\n")
        .filter((line) => !/^\s*#/.test(line))
        .map((line) => line.replace(/\s+#.*$/, ""));
}

export const indentOf = (line: string): number => line.length - line.trimStart().length;

/** The lines under `<indent spaces><key>:`, to the next line at that indent or less. */
export function block(lines: string[], key: string, indent: number): string[] {
    const start = lines.findIndex((line) => line === `${" ".repeat(indent)}${key}:`);
    if (start < 0) throw new Error(`no ${key}: at indent ${indent}`);
    const end = lines.findIndex((line, i) => i > start && line.trim() !== "" && indentOf(line) <= indent);
    return lines.slice(start + 1, end < 0 ? undefined : end);
}

/** A compose file's services, each with its lines. */
export function services(file: string): Map<string, string[]> {
    const found = new Map<string, string[]>();
    let lines: string[] | undefined;
    for (const line of block(codeLines(read(file)), "services", 0)) {
        const name = /^ {2}([A-Za-z0-9_.-]+):\s*$/.exec(line);
        if (name) {
            lines = [];
            found.set(name[1], lines);
        } else {
            lines?.push(line);
        }
    }
    return found;
}

/** A service's own key with a value on its line (`    key: value`). */
export function value(service: string[], key: string): string | undefined {
    const pattern = new RegExp(`^ {4}${key}:\\s*(\\S.*)$`);
    for (const line of service) {
        const match = pattern.exec(line);
        if (match) return match[1].trim();
    }
    return undefined;
}

/** The items of a service's list key, each item's lines, its `- ` line first. */
export function listItems(service: string[], key: string): string[][] {
    const start = service.findIndex((line) => line === `    ${key}:`);
    if (start < 0) return [];
    const found: string[][] = [];
    for (const line of service.slice(start + 1)) {
        if (line.trim() === "") continue;
        if (indentOf(line) <= 4) break;
        if (/^ {6}- /.test(line)) found.push([line]);
        else found[found.length - 1]?.push(line);
    }
    return found;
}

/** A list of scalars: each `- value`, unquoted. */
export function scalars(service: string[], key: string): string[] {
    return listItems(service, key).map((item) =>
        item[0].replace(/^ {6}- /, "").trim().replace(/^(["'])(.*)\1$/, "$2"),
    );
}

/** A list item of keys and values, flattened: `bind.propagation` for a nested key. */
export function fields(item: string[]): Record<string, string> {
    const found: Record<string, string> = {};
    const parents: Array<[number, string]> = [];
    for (const raw of item) {
        const match = /^(\s*)([A-Za-z0-9_.-]+):\s*(.*)$/.exec(raw.replace(/^(\s*)- /, "$1  "));
        if (!match) continue;
        const [, spaces, key, rest] = match;
        while (parents.length && parents[parents.length - 1][0] >= spaces.length) parents.pop();
        const name = [...parents.map(([, parent]) => parent), key].join(".");
        if (rest === "") parents.push([spaces.length, key]);
        else found[name] = rest.trim();
    }
    return found;
}

export const volumes = (service: string[]): Record<string, string>[] => listItems(service, "volumes").map(fields);

/** A service's environment variable, from its `environment:` map. */
export function environment(service: string[], name: string): string | undefined {
    const start = service.findIndex((line) => line === "    environment:");
    if (start < 0) return undefined;
    for (const line of service.slice(start + 1)) {
        if (indentOf(line) <= 4) break;
        const match = new RegExp(`^ {6}${name}:\\s*(.+)$`).exec(line);
        if (match) return match[1].trim();
    }
    return undefined;
}

/**
 * A flow mapping (`{type: bind, bind: {propagation: rshared}}`) flattened as
 * {@link fields} flattens a list item: `bind.propagation` for a nested key.
 * Plain values only, with no comma, brace or quote in them.
 */
export function flowFields(text: string): Record<string, string> {
    const found: Record<string, string> = {};
    let at = 0;
    const skipSpaces = (): void => {
        while (text[at] === " ") at++;
    };
    const mapping = (parents: string[]): void => {
        skipSpaces();
        if (text[at] !== "{") throw new Error(`no { at ${at} of ${text}`);
        at++;
        for (;;) {
            skipSpaces();
            if (text[at] === "}") {
                at++;
                return;
            }
            const colon = text.indexOf(":", at);
            if (colon < 0) throw new Error(`no : after ${at} of ${text}`);
            const key = text.slice(at, colon).trim();
            at = colon + 1;
            skipSpaces();
            if (text[at] === "{") {
                mapping([...parents, key]);
            } else {
                const end = text.slice(at).search(/[,}]/);
                if (end < 0) throw new Error(`no , or } after ${at} of ${text}`);
                found[[...parents, key].join(".")] = text.slice(at, at + end).trim();
                at += end;
            }
            skipSpaces();
            if (text[at] === ",") at++;
        }
    };
    mapping([]);
    skipSpaces();
    if (at !== text.length) throw new Error(`more after the mapping at ${at} of ${text}`);
    return found;
}

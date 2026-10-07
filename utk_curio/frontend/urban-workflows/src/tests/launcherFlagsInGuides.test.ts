/**
 * Every curio.py flag is named in a guide under docs/.
 *
 * A flag is how an operator sets an instance up, so it ships with the guide
 * that tells them about it. The flags are read from the parser in
 * utk_curio/main.py and the guides from the checkout. The backend suite runs
 * in the CI image, which ships no guides, so this check lives here.
 */
import * as fs from "fs";
import * as path from "path";

const REPO_ROOT = path.join(__dirname, "..", "..", "..", "..", "..");
const DOCS = path.join(REPO_ROOT, "docs");

/** #615: the operator settings that were environment-only. */
const OPERATOR_FLAGS = [
    "--guest-llm-provider",
    "--guest-llm-base-url",
    "--guest-llm-model",
    "--media-cache-max-gb",
    "--db-pool-size",
    "--db-pool-overflow",
    "--db-pool-timeout",
    "--package-workers",
    "--js-parallelism",
    "--js-registry-url",
    "--js-block-unpinned",
    "--state-dir",
    "--shared-guest-name",
    "--shared-guest-username",
    "--collab-origins",
    "--collab-namespace",
    "--log-to-stdout",
    "--packages-root",
];

function parserFlags(): string[] {
    const source = fs.readFileSync(path.join(REPO_ROOT, "utk_curio", "main.py"), "utf-8");
    const flags = Array.from(source.matchAll(/add_argument\(\s*"(--[a-z0-9-]+)"/g), (m) => m[1]);
    return Array.from(new Set(flags)).sort();
}

function readGuides(): Array<[string, string]> {
    return fs.readdirSync(DOCS)
        .filter((name) => name.endsWith(".md"))
        .sort()
        .map((name): [string, string] => [name, fs.readFileSync(path.join(DOCS, name), "utf-8")]);
}

function guidesNaming(flag: string, guides: Array<[string, string]>): string[] {
    const escaped = flag.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const pattern = new RegExp(`${escaped}(?![a-z0-9-])`);
    return guides.filter(([, text]) => pattern.test(text)).map(([name]) => name);
}

test.each(OPERATOR_FLAGS)("a guide names %s", (flag) => {
    expect(guidesNaming(flag, readGuides())).not.toEqual([]);
});

test("every curio.py flag is named in a guide", () => {
    const guides = readGuides();
    const flags = parserFlags();
    // The parser is read as text: finding next to no flags means the pattern
    // stopped matching how main.py declares them, not that all is documented.
    expect(flags.length).toBeGreaterThan(30);
    expect(flags.filter((flag) => guidesNaming(flag, guides).length === 0)).toEqual([]);
});

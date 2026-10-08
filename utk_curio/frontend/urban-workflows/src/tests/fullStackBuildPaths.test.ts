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
import { REPO_ROOT, copiedIntoTheImage, fileIn, pathsFilters, startsARun } from "./_support/workflowPaths";

const WORKFLOW = ".github/workflows/docker-compose.yml";
const EVENTS = ["push", "pull_request"];

/** Files the jobs read from the checkout that the image does not copy, and their readers. */
const READ_FROM_THE_CHECKOUT: Array<[string, string]> = [
    [".nvmrc", "setup-node in jest and preview-runner, and scripts/check_node_pins.py"],
    [".node-version", "scripts/check_node_pins.py"],
    ["docker-compose.deploy.yml", "test-gpu's check of the production deploy configuration"],
];

describe(`the paths filters of ${WORKFLOW}`, () => {
    const filters = pathsFilters(WORKFLOW);
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
        expect(copied.filter((source) => !startsARun(fileIn(source), patterns(event)))).toEqual([]);
    });

    const readers = EVENTS.flatMap((event) =>
        READ_FROM_THE_CHECKOUT.map(([file, reader]): [string, string, string] => [event, file, reader]),
    );
    test.each(readers)("on %s, a change to %s starts a build (read by %s)", (event, file) => {
        expect(startsARun(file, patterns(event))).toBe(true);
    });

    // launcherFlagsInGuides.test.ts reads every guide, solveStopReasonsDocs.test.ts
    // docs/ARCHITECTURE.md, and the e2e examples checks docs/README.md.
    test.each(EVENTS)("on %s, a change to a guide under docs/ starts a build", (event) => {
        const guides = fs
            .readdirSync(path.join(REPO_ROOT, "docs"))
            .filter((name) => name.endsWith(".md"))
            .map((name) => `docs/${name}`);
        expect(guides.length).toBeGreaterThan(5);
        expect(guides.filter((file) => !startsARun(file, patterns(event)))).toEqual([]);
    });
});

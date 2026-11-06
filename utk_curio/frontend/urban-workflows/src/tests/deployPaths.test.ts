/**
 * A change to anything the deployed image copies redeploys curio-dev, once.
 *
 * .github/workflows/bump-version.yml runs on a push to main that changes a
 * file its `paths` filter matches, bumps the version and dispatches
 * .github/workflows/deploy.yml for curio-dev, which builds the image from the
 * Dockerfile. A folder the image copies that the filter misses can change on
 * main while curio-dev keeps serving the old one. What the image copies is
 * read from the Dockerfile, as fullStackBuildPaths.test.ts reads it.
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
});

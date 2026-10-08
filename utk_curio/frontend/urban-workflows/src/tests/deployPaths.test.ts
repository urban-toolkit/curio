/**
 * A change to anything the deployed image copies redeploys curio-dev.
 *
 * .github/workflows/deploy.yml deploys main to curio-dev on a push that
 * changes a file its `paths` filter matches, and the deploy builds the image
 * from the Dockerfile. A folder the image copies that the filter misses can
 * change on main while curio-dev keeps serving the old one. What the image
 * copies is read from the Dockerfile, as fullStackBuildPaths.test.ts reads it.
 */
import { copiedIntoTheImage, fileIn, pathsFilters, startsARun } from "./_support/workflowPaths";

const WORKFLOW = ".github/workflows/deploy.yml";

/**
 * What the image carries only for CI's packaging tests, as the Dockerfile's
 * comment above their COPY says: the deployed app never reads them, so a
 * change to them alone needs no deploy.
 */
const FOR_CI_ONLY = ["pyproject.toml", "MANIFEST.in", "setup.py"];

describe(`the paths filter of ${WORKFLOW}`, () => {
    const patterns = pathsFilters(WORKFLOW).get("push") ?? [];

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
});

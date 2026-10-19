/**
 * CI's image holds what `curio.py setup --with-examples` installs; the
 * deploy's image does not change.
 *
 * The Dockerfile's CURIO_CI_SETUP build argument adds those libraries. A CI
 * stack boots with CURIO_SKIP_DEP_INSTALL=1 and installs nothing, so a CI
 * overlay that skips the install must also build the CI image, and
 * build-image must pass the argument. The deploy builds from
 * docker-compose.yml and docker-compose.deploy.yml, which pass neither. A job
 * that runs `scripts/test.sh --skip-setup` on the runner, not in the
 * container, first copies the image's packages there. The backend suite runs
 * in the image, which ships no compose file or workflow, so this check lives
 * here.
 */
import { read } from "./_support/workflowPaths";

const WORKFLOW = ".github/workflows/docker-compose.yml";
const CI_OVERLAYS = [
    "docker-compose.ci.yml",
    "docker-compose.ci-isolated.yml",
    "docker-compose.ci-exec-user.yml",
    "docker-compose.ci-stress.yml",
];
const DEPLOY_FILES = ["docker-compose.yml", "docker-compose.deploy.yml", ".github/workflows/deploy.yml"];

/** The workflow's jobs, keyed by name, as the text under `jobs:`. */
function jobs(): Map<string, string> {
    const text = read(WORKFLOW);
    const body = text.slice(text.search(/^jobs:\s*$/m));
    const found = new Map<string, string>();
    for (const block of body.split(/^(?= {2}[a-z0-9-]+:\s*$)/m).slice(1)) {
        found.set(block.trim().split(":")[0], block);
    }
    return found;
}

describe("CI's image and the deploy's", () => {
    test.each(CI_OVERLAYS)("%s builds the CI image and boots installing nothing", (file) => {
        const text = read(file);
        expect(text).toMatch(/^ {6}args:\n {8}CURIO_CI_SETUP: "1"$/m);
        expect(text).toMatch(/^ {6}- CURIO_SKIP_DEP_INSTALL=1$/m);
    });

    test.each(DEPLOY_FILES)("%s passes neither", (file) => {
        const text = read(file);
        expect(text).not.toContain("CURIO_CI_SETUP");
        expect(text).not.toContain("CURIO_SKIP_DEP_INSTALL");
    });

    test("the Dockerfile builds the deploy's image unless asked", () => {
        expect(read("Dockerfile")).toMatch(/^ARG CURIO_CI_SETUP=0$/m);
    });

    test("build-image builds the CI image", () => {
        expect(jobs().get("build-image")).toMatch(/^ {10}build-args: CURIO_CI_SETUP=1$/m);
    });

    test("a job that runs test.sh --skip-setup on the runner takes the image's packages first", () => {
        const onTheRunner = Array.from(jobs()).filter(
            ([, job]) => /scripts\/test\.sh[^\n]*--skip-setup/.test(job) && !/exec -T[^\n]*\\\n[\s\S]*?scripts\/test\.sh/.test(job),
        );
        expect(onTheRunner.map(([name]) => name).sort()).toEqual(["e2e-desktop", "test-gpu", "test-isolated"]);
        const without = onTheRunner
            .filter(([, job]) => !/runner-env: "true"|uses: \.\/\.github\/actions\/image-env/.test(job))
            .map(([name]) => name);
        expect(without).toEqual([]);
    });
});

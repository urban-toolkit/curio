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
 *
 * stop-stack ends every job that starts a stack with
 * scripts/ci_image_cleanup.sh (tested in the backend suite), which on an
 * arcade runner removes images only once CURIO_CI_OWN_IMAGE says the job has
 * one of its own. So every such job must say so: start-stack after its pull,
 * or the job after it builds its image.
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

describe("Removing CI images on self-hosted runners", () => {
    const MARK = 'echo "CURIO_CI_OWN_IMAGE=1" >> "$GITHUB_ENV"';

    test("stop-stack runs the cleanup script", () => {
        expect(read(".github/actions/stop-stack/action.yml")).toContain(
            'bash "$GITHUB_WORKSPACE/scripts/ci_image_cleanup.sh" "$PROJECT"',
        );
    });

    test("start-stack says the job has an image once it has pulled and named it", () => {
        expect(read(".github/actions/start-stack/action.yml")).toContain(
            `docker tag "$IMAGE" "$PROJECT-curio"\n        ${MARK}`,
        );
    });

    test("every job that ends with stop-stack says when it has an image of its own", () => {
        const stopping = Array.from(jobs()).filter(([, job]) => job.includes("uses: ./.github/actions/stop-stack"));
        expect(stopping.map(([name]) => name).sort()).toEqual([
            "e2e-desktop",
            "test-exec-user",
            "test-gpu",
            "test-gpu-stress",
            "test-isolated",
            "unit",
        ]);
        const silent = stopping
            .filter(
                ([, job]) =>
                    !job.includes("uses: ./.github/actions/start-stack") &&
                    !/docker compose -p \S+ build --parallel\n\s+echo "CURIO_CI_OWN_IMAGE=1" >> "\$GITHUB_ENV"/.test(job),
            )
            .map(([name]) => name);
        expect(silent).toEqual([]);
    });
});

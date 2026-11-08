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
 * No CI image outlives its job on a self-hosted runner: the image is about
 * 17 GB, and the 44 arcade runners share one disk, which the images they kept
 * between jobs filled on 11-08. So every job that pulls, builds or takes an
 * image there runs scripts/ci_image_cleanup.sh (tested in the backend suite)
 * at its end whatever its steps did, through stop-stack or a step of its own,
 * and its first step removes what a job ended before its cleanup left. On a
 * GitHub-hosted runner start-stack and build-image make room for the image
 * first (scripts/ci_disk.sh, tested in the backend suite).
 *
 * On an arcade runner those packages are the image's own folder, mounted in
 * place by a helper container (scripts/ci_image_python.sh, tested in the
 * backend suite): copied, they were 9.4 GB of disk writes per job, and a run
 * starts up to 15 such jobs at once on arcade's one disk. The helper holds its
 * image and the mount holds its files, so every job that takes them on a
 * self-hosted runner lets them go, and stop-stack does so before the image
 * cleanup.
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
        // build-image lists a filtered run's selected e2e tests the way the e2e jobs collect them.
        expect(onTheRunner.map(([name]) => name).sort()).toEqual([
            "build-image",
            "e2e-desktop",
            "test-gpu",
            "test-isolated",
        ]);
        const without = onTheRunner
            .filter(([, job]) => !/runner-env: "true"|uses: \.\/\.github\/actions\/image-env/.test(job))
            .map(([name]) => name);
        expect(without).toEqual([]);
    });
});

describe("The image's Python packages on the runner", () => {
    const IMAGE_ENV = ".github/actions/image-env/action.yml";
    const STOP_STACK = ".github/actions/stop-stack/action.yml";

    test("image-env takes them through the script, which mounts them in place on arcade", () => {
        const action = read(IMAGE_ENV);
        expect(action).toContain('run: bash "$GITHUB_WORKSPACE/scripts/ci_image_python.sh" take "$IMAGE"');
        expect(action).not.toContain("docker cp");
        const script = read("scripts/ci_image_python.sh");
        expect(script).toContain("--mount \"type=bind,source=$site,target=/mnt/site,bind-propagation=rshared\"");
        expect(script).toContain("mount --bind -o ro $SITE_IN_IMAGE /mnt/site");
    });

    test("stop-stack lets them go before it removes images", () => {
        const text = read(STOP_STACK);
        const release = text.indexOf('bash "$GITHUB_WORKSPACE/scripts/ci_image_python.sh" release');
        expect(release).toBeGreaterThan(-1);
        expect(release).toBeLessThan(text.indexOf('bash "$GITHUB_WORKSPACE/scripts/ci_image_cleanup.sh"'));
    });

    test("every job that takes them on a self-hosted runner lets them go, whatever its steps did", () => {
        const taking = Array.from(jobs()).filter(([, job]) =>
            /runner-env: "true"|uses: \.\/\.github\/actions\/image-env/.test(job),
        );
        expect(taking.map(([name]) => name).sort()).toEqual([
            "build-image",
            "e2e-desktop",
            "test-desktop-stress",
            "test-gpu",
            "test-gpu-stress",
            "test-isolated",
        ]);
        // test-desktop-stress runs on a fresh GitHub-hosted runner, which copies them.
        const selfHosted = taking.filter(([, job]) => !/^ {4}runs-on: ubuntu-latest$/m.test(job));
        expect(selfHosted.map(([name]) => name)).not.toContain("test-desktop-stress");
        const holding = selfHosted
            .filter(
                ([, job]) =>
                    !/uses: \.\/\.github\/actions\/stop-stack\n {8}if: always\(\)/.test(job) &&
                    !/if: always\(\)[^\n]*\n {8}run: \|\n {10}bash scripts\/ci_image_python\.sh release$/m.test(job),
            )
            .map(([name]) => name);
        expect(holding).toEqual([]);
    });
});

describe("No CI image outlives its job on a self-hosted runner", () => {
    const START_STACK = ".github/actions/start-stack/action.yml";
    const STOP_STACK = ".github/actions/stop-stack/action.yml";
    /** A step that pulls, builds or takes the CI image. */
    const PLACES_AN_IMAGE = /uses: \.\/\.github\/actions\/(start-stack|image-env)|runner-env: "true"|docker compose -p \S+ build|docker pull/;
    const STOP_STACK_ALWAYS = /uses: \.\/\.github\/actions\/stop-stack\n {8}if: always\(\)/;
    const CLEANUP_ALWAYS = /if: always\(\)[^\n]*\n {8}run: \|\n(?: {10}[^\n]*\n)*? {10}[^\n]*bash scripts\/ci_image_cleanup\.sh/;

    /** The jobs that can put a CI image on a self-hosted runner's daemon. */
    function placing(): [string, string][] {
        return Array.from(jobs()).filter(
            ([, job]) => PLACES_AN_IMAGE.test(job) && !/^ {4}runs-on: ubuntu-latest$/m.test(job),
        );
    }

    test("stop-stack runs the cleanup script", () => {
        expect(read(STOP_STACK)).toContain('bash "$GITHUB_WORKSPACE/scripts/ci_image_cleanup.sh"\n');
    });

    test("every job that puts a CI image on a self-hosted daemon removes it at its end, whatever its steps did", () => {
        expect(placing().map(([name]) => name).sort()).toEqual([
            "build-image",
            "e2e-desktop",
            "test-exec-user",
            "test-gpu",
            "test-gpu-stress",
            "test-isolated",
            "unit",
        ]);
        const keeping = placing()
            .filter(([, job]) => !STOP_STACK_ALWAYS.test(job) && !CLEANUP_ALWAYS.test(job))
            .map(([name]) => name);
        expect(keeping).toEqual([]);
    });

    test("skill-evals, which pulls main's image on its arcade runner, removes it at its end", () => {
        expect(read(".github/workflows/skill-evals.yml")).toMatch(STOP_STACK_ALWAYS);
    });

    test("each such job's first step removes the CI images a job ended before its cleanup left", () => {
        const text = read(WORKFLOW);
        const start = text.indexOf("- &reclaim");
        const reclaim = text.slice(start, text.indexOf("- name: ", start + 1));
        expect(reclaim).toContain('grep -E "^(curio-ci(-[a-z-]+)?-curio|ghcr\\.io/${GITHUB_REPOSITORY,,}-ci):"');
        expect(reclaim).toContain("| xargs -r docker image rm > /dev/null 2>&1 || true");
        expect(reclaim).not.toMatch(/docker image rm -f|docker rmi/);
        const late = placing()
            .filter(([, job]) => !/^ {4}steps:\n(?: {6}#[^\n]*\n)* {6}- [&*]reclaim$/m.test(job))
            .map(([name]) => name);
        expect(late).toEqual([]);
    });

    test("no job says whether it has an image of its own any more", () => {
        for (const file of [WORKFLOW, ".github/workflows/skill-evals.yml", START_STACK, STOP_STACK, "scripts/ci_image_cleanup.sh"]) {
            expect([file, read(file).includes("CURIO_CI_OWN_IMAGE")]).toEqual([file, false]);
        }
    });

    test("start-stack and build-image make room on a GitHub-hosted runner before the image comes", () => {
        const startStack = read(START_STACK);
        const drop = startStack.indexOf("bash scripts/ci_disk.sh drop-tools");
        expect(drop).toBeGreaterThan(-1);
        expect(drop).toBeLessThan(startStack.indexOf('docker pull --quiet "$IMAGE"'));
        expect(startStack.indexOf("bash scripts/ci_disk.sh wait-tools")).toBeGreaterThan(
            startStack.indexOf("did not become healthy"),
        );
        const buildImage = jobs().get("build-image") ?? "";
        const dropBeforeBuild = buildImage.indexOf("bash scripts/ci_disk.sh drop-tools");
        expect(dropBeforeBuild).toBeGreaterThan(-1);
        expect(dropBeforeBuild).toBeLessThan(buildImage.indexOf("uses: docker/build-push-action"));
    });

    test("stop-stack says how much disk was free at the job's end, before the teardown", () => {
        const text = read(STOP_STACK);
        const free = text.indexOf('scripts/ci_disk.sh" free');
        expect(free).toBeGreaterThan(-1);
        expect(free).toBeLessThan(text.indexOf('docker compose -p "$PROJECT" down'));
    });
});

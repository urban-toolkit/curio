/**
 * The weights a model package's fetch names are in neither git, the image
 * nor the pip package. The server downloads them the first time a node runs
 * the model, into a host folder a deployment mounts at /model-weights, which
 * isolated node code reads in place: docker-compose.deploy.yml mounts
 * ./model-weights there, and each stack of the Deploy workflow mounts the one
 * folder both share instead and passes --model-weights-dir /model-weights,
 * for a release whose launcher reads it. The server writes the folder, so it
 * is mounted writable, and it is root's, the account the container's server
 * runs as: every account reads it and no other writes it.
 */
import { read } from "./_support/workflowPaths";

describe("The deploy's fetched model weights", () => {
    const workflow = read(".github/workflows/deploy.yml");

    test("each stack mounts the shared folder for the server to write and names it, for a release that reads it", () => {
        expect(workflow.match(/grep -q -e '"--model-weights-dir"' utk_curio\/main\.py/g)).toHaveLength(2);
        expect(workflow.match(/weights_args=', "--model-weights-dir", "\/model-weights"'/g)).toHaveLength(2);
        // Curio's volumes in the site file: the weights folder first, when
        // the release reads it, then the bucket mounts' bind.
        expect(
            workflow.match(
                /^( +)if \[ -n "\$weights_args" \]; then\n\1 {2}curio_volumes='"\/srv\/curio-model-weights:\/model-weights"'\n\1fi$/gm,
            ),
        ).toHaveLength(2);
        expect(
            workflow.match(/printf ' {4}volumes: \[%s\]\\n' "\$curio_volumes" >> docker-compose\.site\.yml/g),
        ).toHaveLength(2);
        expect(workflow).not.toMatch(/model-weights:ro/);
        // Before the top-level secrets the site file may end with.
        for (const job of workflow.split(/^ {2}deploy-(?:dev|stable):$/m).slice(1)) {
            expect(job.indexOf("volumes: [")).toBeGreaterThan(-1);
            expect(job.indexOf("volumes: [")).toBeLessThan(job.indexOf("secrets: [curio_llm_endpoint]"));
            expect(job.indexOf("curio_volumes='")).toBeGreaterThan(-1);
            expect(job.indexOf("curio_volumes='")).toBeLessThan(job.indexOf("volumes: ["));
        }
    });

    test("each stack gives the folder to root, readable by every account and writable by no other", () => {
        const owned =
            "docker run --rm -v /srv/curio-model-weights:/weights alpine sh -c " +
            "'chown -R 0:0 /weights && chmod -R u+rwX,go+rX,go-w /weights' < /dev/null";
        expect(workflow.split(owned)).toHaveLength(3);
        // Before the stack starts with the folder mounted.
        for (const job of workflow.split(/^ {2}deploy-(?:dev|stable):$/m).slice(1)) {
            expect(job.indexOf(owned)).toBeGreaterThan(-1);
            expect(job.indexOf(owned)).toBeLessThan(job.indexOf("volumes: ["));
        }
    });

    test("the deploy overlay mounts a folder of the checkout there, for the server to write", () => {
        const overlay = read("docker-compose.deploy.yml");
        expect(overlay).toMatch(/^ {6}- \.\/model-weights:\/model-weights$/m);
        expect(overlay).not.toMatch(/model-weights:ro/);
    });

    test("the weights are in neither git nor the image", () => {
        const gitignore = read(".gitignore");
        expect(gitignore).toMatch(/^\/packages\/\*\/models\/\*\/$/m);
        expect(gitignore).toMatch(/^\/model-weights\/$/m);
        const dockerignore = read(".dockerignore");
        expect(dockerignore).toMatch(/^packages\/\*\/models\/\*\/\*\*$/m);
        expect(dockerignore).toMatch(/^model-weights$/m);
    });
});

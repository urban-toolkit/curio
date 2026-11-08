/**
 * The weights a model package's operator fetches (its model block's fetch)
 * are in neither git, the image nor the pip package. A deployment keeps them
 * in a host folder, which scripts/fetch_model_weights.py --into fills, and
 * mounts it read-only at /model-weights: docker-compose.deploy.yml mounts
 * ./model-weights there, and each stack of the Deploy workflow mounts the one
 * folder both share instead and passes --model-weights-dir /model-weights,
 * for a release whose launcher reads it.
 */
import { read } from "./_support/workflowPaths";

describe("The deploy's fetched model weights", () => {
    const workflow = read(".github/workflows/deploy.yml");

    test("each stack mounts the shared folder read-only and names it, for a release that reads it", () => {
        expect(workflow.match(/grep -q -e '"--model-weights-dir"' utk_curio\/main\.py/g)).toHaveLength(2);
        expect(workflow.match(/weights_args=', "--model-weights-dir", "\/model-weights"'/g)).toHaveLength(2);
        expect(
            workflow.match(/printf ' {4}volumes: \["\/srv\/curio-model-weights:\/model-weights:ro"\]\\n'/g),
        ).toHaveLength(2);
        // Before the top-level secrets the site file may end with.
        for (const job of workflow.split(/^ {2}deploy-(?:dev|stable):$/m).slice(1)) {
            expect(job.indexOf("volumes: [")).toBeGreaterThan(-1);
            expect(job.indexOf("volumes: [")).toBeLessThan(job.indexOf("secrets: [curio_llm_endpoint]"));
        }
    });

    test("the deploy overlay mounts a folder of the checkout there, read-only", () => {
        expect(read("docker-compose.deploy.yml")).toMatch(/^ {6}- \.\/model-weights:\/model-weights:ro$/m);
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

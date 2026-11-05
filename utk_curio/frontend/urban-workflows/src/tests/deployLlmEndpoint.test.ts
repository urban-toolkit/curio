/**
 * The Deploy workflow gives each stack its LLM endpoint from its environment's
 * secrets, CURIO_DEPLOY_API_KEY and CURIO_DEPLOY_BASE_URL. Neither value is on
 * a command line, in git or in the image: each job reads them through a step's
 * env, masks the URL's host, and sends them to the server as a file the stack
 * mounts read-only, named on curio.py's command line by its path alone, only
 * for a release whose launcher reads it.
 */
import { read } from "./_support/workflowPaths";

const WORKFLOW = ".github/workflows/deploy.yml";

describe("The deploy's LLM endpoint", () => {
    const text = read(WORKFLOW);

    test("each job reads the two secrets through a step's env only", () => {
        const lines = text.split("\n").filter((line) => line.includes("secrets.CURIO_DEPLOY_"));
        expect(lines).toHaveLength(4);
        for (const line of lines) {
            expect(line).toMatch(/^ {10}CURIO_DEPLOY_(API_KEY|BASE_URL): \$\{\{ secrets\.CURIO_DEPLOY_\1 \}\}$/);
        }
    });

    test("each job masks the URL's host before it sends anything", () => {
        const steps = text.split(/^ {6}- name: Send the LLM endpoint$/m).slice(1);
        expect(steps).toHaveLength(2);
        for (const step of steps) {
            const mask = step.indexOf("python3 scripts/ci_skill_evals.py mask --env CURIO_DEPLOY_BASE_URL");
            expect(mask).toBeGreaterThan(-1);
            expect(mask).toBeLessThan(step.indexOf("| ssh "));
        }
    });

    test("each stack mounts the file and names only its path, for a release that reads it", () => {
        expect(text.match(/grep -q -e '"--llm-endpoint-file"' utk_curio\/main\.py/g)).toHaveLength(2);
        expect(text.match(/\\"--llm-endpoint-file\\", \\"\/run\/secrets\/curio_llm_endpoint\\"/g)).toHaveLength(2);
        expect(text.match(/file: \.\/\.secrets\/llm-endpoint/g)).toHaveLength(2);
    });

    test("the file is in neither git nor the image", () => {
        expect(read(".gitignore")).toMatch(/^\/\.secrets\/$/m);
        expect(read(".dockerignore")).toMatch(/^\/\.secrets\/$/m);
    });
});

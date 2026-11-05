/**
 * The Deploy workflow gives each stack its LLM endpoint from its environment's
 * secrets, CURIO_DEPLOY_API_KEY and CURIO_DEPLOY_BASE_URL, and the repository
 * variable CURIO_DEPLOY_MODELS. Neither secret is on a command line, in git or
 * in the image: each job reads them through a step's env, masks the URL's
 * host, and sends them with the models to the server as one endpoint file the
 * stack mounts read-only. curio.py's command line names that file by its path
 * alone, and only for a release whose launcher reads it.
 */
import { read } from "./_support/workflowPaths";

const WORKFLOW = ".github/workflows/deploy.yml";

describe("The deploy's LLM endpoint", () => {
    const text = read(WORKFLOW);
    const sends = text.split(/^ {6}- name: Send the LLM endpoint$/m).slice(1);

    test("each job reads the two secrets and the models through a step's env only", () => {
        const lines = text.split("\n").filter((line) => /(secrets|vars)\.CURIO_DEPLOY_/.test(line));
        expect(lines).toHaveLength(6);
        for (const line of lines) {
            expect(line).toMatch(/^ {10}CURIO_DEPLOY_(API_KEY|BASE_URL|MODELS): \$\{\{ (secrets|vars)\.CURIO_DEPLOY_\1 \}\}$/);
        }
        expect(sends).toHaveLength(2);
        for (const send of sends) {
            expect(send.slice(0, send.indexOf("run: |"))).toContain("vars.CURIO_DEPLOY_MODELS");
        }
    });

    test("each job masks the URL's host before it sends anything", () => {
        for (const send of sends) {
            const mask = send.indexOf("python3 scripts/ci_skill_evals.py mask --env CURIO_DEPLOY_BASE_URL");
            expect(mask).toBeGreaterThan(-1);
            expect(mask).toBeLessThan(send.indexOf("| ssh "));
        }
    });

    test("the file holds the endpoint with its models, as one section", () => {
        for (const send of sends) {
            expect(send).toContain("printf '[This Curio]\\nbase_url=%s\\napi_key=%s\\nmodels=%s\\n'");
        }
    });

    test("each stack mounts the file and names only its path, for a release that reads it", () => {
        expect(text.match(/grep -q -e '"--llm-endpoint-file"' utk_curio\/main\.py/g)).toHaveLength(2);
        expect(text.match(/llm_args=', "--llm-endpoint-file", "\/run\/secrets\/curio_llm_endpoint"'/g)).toHaveLength(2);
        expect(text.match(/file: \.\/\.secrets\/llm-endpoint/g)).toHaveLength(2);
        expect(text).not.toMatch(/--llm-(models|model|provider|base-url)\b/);
    });

    test("the file is in neither git nor the image", () => {
        expect(read(".gitignore")).toMatch(/^\/\.secrets\/$/m);
        expect(read(".dockerignore")).toMatch(/^\/\.secrets\/$/m);
    });
});

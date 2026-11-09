/**
 * Both stacks let Cache files copy a bucket file of up to 8 GiB: SideSeeing's
 * longest walks are 7 GiB videos, over the 4 GiB a launcher takes by default.
 * Stable deploys a release, and a launcher older than the flag refuses it and
 * does not start, so each job passes it only when its checkout's main.py
 * declares it, as it passes --llm-endpoint-file.
 */
import { read } from "./_support/workflowPaths";

const WORKFLOW = ".github/workflows/deploy.yml";

describe("The deploy's limit on one cached file", () => {
    const text = read(WORKFLOW);

    test("each stack passes 8 GiB, only for a launcher that declares the flag", () => {
        expect(text.match(/grep -q -e '"--media-cache-max-file-gb"' utk_curio\/main\.py; then/g)).toHaveLength(2);
        expect(text.match(/cache_args=', "--media-cache-max-file-gb", "8"'/g)).toHaveLength(2);
        expect(text.match(/cache_args=""/g)).toHaveLength(2);
    });

    test("each stack's command line carries it", () => {
        const commands = text.match(/printf ' {4}command: \[[^\n]*/g) ?? [];
        expect(commands).toHaveLength(2);
        for (const command of commands) {
            expect(command).toMatch(
                /"24576"%s%s%s%s%s\]\\n' "\$llm_args" "\$weights_args" "\$cache_args" "\$download_args" "\$mounts_args" >> docker-compose\.site\.yml$/,
            );
        }
    });

    test("each stack sets it before its command line names it", () => {
        const jobs = text.split(/^ {2}deploy-(?:dev|stable):$/m).slice(1);
        expect(jobs).toHaveLength(2);
        for (const job of jobs) {
            const command = job.search(/printf ' {4}command: \[/);
            expect(command).toBeGreaterThan(-1);
            expect(job.indexOf('cache_args=""')).toBeGreaterThan(-1);
            expect(job.indexOf('cache_args=""')).toBeLessThan(command);
            expect(job.indexOf(`cache_args=', "--media-cache-max-file-gb", "8"'`)).toBeLessThan(command);
            expect(job.indexOf(`cache_args=', "--media-cache-max-file-gb", "8"'`)).toBeGreaterThan(-1);
        }
    });
});

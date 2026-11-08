/**
 * Both stacks add a bucket table's file of up to 2 GiB: a month of SAGE-IDOT's
 * detections on data.urbantk.org is a JSON Lines file of up to 1.7 GB, over
 * the 1 GiB a launcher takes by default. Stable deploys a release, and a
 * launcher older than the flag refuses it and does not start, so each job
 * passes it only when its checkout's main.py declares it, as it passes
 * --model-weights-dir.
 */
import { read } from "./_support/workflowPaths";

describe("The deploy's download limit", () => {
    const text = read(".github/workflows/deploy.yml");

    test("each stack passes 2048 MB, only for a launcher that declares the flag", () => {
        expect(text.match(/grep -q -e '"--discovery-max-download-mb"' utk_curio\/main\.py; then/g)).toHaveLength(2);
        expect(text.match(/download_args=', "--discovery-max-download-mb", "2048"'/g)).toHaveLength(2);
        expect(text.match(/download_args=""/g)).toHaveLength(2);
    });

    test("each stack's command line carries it, with an argument for each %s", () => {
        const commands = text.match(/printf ' {4}command: \[[^\n]*/g) ?? [];
        expect(commands).toHaveLength(2);
        for (const command of commands) {
            const args = command.match(/ "\$[a-z]+_args"/g) ?? [];
            expect(args).toContain(' "$download_args"');
            expect(command.match(/%s/g)).toHaveLength(args.length);
        }
    });
});

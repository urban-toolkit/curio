/**
 * Both stacks give every hosted guest SAM 3, so a guest, who adds no package
 * and installs no library, runs its Track Objects on the host's GPU. Stable
 * deploys a release, and a launcher older than the flag refuses it and does
 * not start, so each job passes it only when its checkout's main.py declares
 * it, as it passes --model-weights-dir.
 */
import { read } from "./_support/workflowPaths";

describe("The deploy's guest packages", () => {
    const text = read(".github/workflows/deploy.yml");

    test("each stack names SAM 3, only for a launcher that declares the flag", () => {
        expect(text.match(/grep -q -e '"--guest-packages"' utk_curio\/main\.py; then/g)).toHaveLength(2);
        expect(text.match(/guest_args=', "--guest-packages", "model\.curio\.sam3@1"'/g)).toHaveLength(2);
        expect(text.match(/guest_args=""/g)).toHaveLength(2);
    });

    test("each stack's command line carries it, with an argument for each %s", () => {
        const commands = text.match(/printf ' {4}command: \[[^\n]*/g) ?? [];
        expect(commands).toHaveLength(2);
        for (const command of commands) {
            const args = command.match(/ "\$[a-z]+_args"/g) ?? [];
            expect(args).toContain(' "$guest_args"');
            expect(command.match(/%s/g)).toHaveLength(args.length);
        }
    });

    test("each stack sets it before its command line names it", () => {
        const jobs = text.split(/^ {2}deploy-(?:dev|stable):$/m).slice(1);
        expect(jobs).toHaveLength(2);
        for (const job of jobs) {
            const command = job.search(/printf ' {4}command: \[/);
            const reset = job.indexOf('guest_args=""');
            const named = job.indexOf(`guest_args=', "--guest-packages", "model.curio.sam3@1"'`);
            expect(command).toBeGreaterThan(-1);
            expect(reset).toBeGreaterThan(-1);
            expect(named).toBeGreaterThan(reset);
            expect(named).toBeLessThan(command);
        }
    });
});

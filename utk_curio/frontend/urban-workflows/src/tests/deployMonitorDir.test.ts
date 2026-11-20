/**
 * Both stacks keep the monitor's histories (open files, LLM tokens) across
 * deploys: each in a folder of its own outside its checkout,
 * /srv/curio-monitor/dev and /srv/curio-monitor/stable, which its site file
 * binds into Curio's container at /monitor and names with --monitor-dir, for
 * a release whose launcher has the flag, which each job detects as it detects
 * --model-weights-dir. Dev's deploy deletes its checkout's .curio, where the
 * histories are by default. Docker makes the folder, root's, as the server
 * runs. The files are read as text, as deployBucketMounts.test.ts reads
 * deploy.yml.
 */
import { flowFields } from "./_support/composeFile";
import { read } from "./_support/workflowPaths";

const WORKFLOW = ".github/workflows/deploy.yml";

const text = read(WORKFLOW);
const jobs = text.split(/^ {2}deploy-(?:dev|stable):$/m).slice(1);
/** Each stack's name and its job's text. */
const STACKS: Array<[string, string]> = [
    ["dev", jobs[0] ?? ""],
    ["stable", jobs[1] ?? ""],
];

/** Where `needle` is in `haystack`, which must hold it once. */
function once(haystack: string, needle: string): number {
    const first = haystack.indexOf(needle);
    expect(first).toBeGreaterThan(-1);
    expect(haystack.indexOf(needle, first + 1)).toBe(-1);
    return first;
}

describe("The deploy's monitor folder", () => {
    test("the two jobs are dev's and stable's", () => {
        expect(jobs).toHaveLength(2);
        expect(STACKS[0][1]).toContain("\n          cd /srv/curio-dev\n");
        expect(STACKS[1][1]).toContain("\n          cd /srv/curio\n");
    });

    test("each stack names it only for a launcher that declares the flag", () => {
        expect(read("utk_curio/main.py")).toMatch(/add_argument\(\s*"--monitor-dir"/);
        for (const [, job] of STACKS) {
            const detect =
                /^( +)if grep -q -e '"--monitor-dir"' utk_curio\/main\.py; then\n\1 {2}monitor_args=', "--monitor-dir", "\/monitor"'\n\1fi$/gm;
            expect(job.match(detect)).toHaveLength(1);
            expect(once(job, 'monitor_args=""')).toBeLessThan(job.indexOf(`grep -q -e '"--monitor-dir"'`));
        }
        expect(text.match(/monitor_args='/g)).toHaveLength(2);
    });

    test("each stack's command line passes it, after setting it, before the bucket mounts", () => {
        for (const [, job] of STACKS) {
            const command = job.match(/printf ' {4}command: \[[^\n]*/)?.[0] ?? "";
            expect(command).toMatch(/ "\$monitor_args" "\$mounts_args" "\$processes_args" >> docker-compose\.site\.yml$/);
            expect(command.match(/%s/g)).toHaveLength((command.match(/ "\$[a-z]+_args"/g) ?? []).length);
            expect(job.indexOf(`grep -q -e '"--monitor-dir"'`)).toBeLessThan(job.search(/printf ' {4}command: \[/));
        }
    });

    test("each stack binds its own folder outside its checkout at /monitor, which Docker makes", () => {
        for (const [stack, job] of STACKS) {
            expect(job.match(/^ +monitor_dir=.*$/gm)).toEqual([
                expect.stringMatching(new RegExp(`^ +monitor_dir=/srv/curio-monitor/${stack}$`)),
            ]);
            const bind = /^( +)if \[ -n "\$monitor_args" \]; then\n\1 {2}curio_volumes="\$\{curio_volumes:\+\$curio_volumes, \}(\{[^"\n]*\})"\n\1fi$/m.exec(job);
            expect(bind).not.toBeNull();
            expect(flowFields(bind?.[2] ?? "")).toEqual({
                type: "bind",
                source: "$monitor_dir",
                target: "/monitor",
                "bind.create_host_path": "true",
            });
            // Set after the weights folder, which starts the list, and before
            // the list is written.
            const at = job.indexOf(bind?.[0] ?? "");
            expect(job.indexOf("curio_volumes='")).toBeLessThan(at);
            expect(at).toBeLessThan(once(job, `printf '    volumes: [%s]\\n' "$curio_volumes" >> docker-compose.site.yml`));
        }
        // The two stacks keep apart, and Docker makes each folder, root's.
        expect(text).not.toMatch(/mkdir[^\n]*curio-monitor/);
        // Dev's deploy wipes its checkout's .curio, which the folder is outside.
        expect(STACKS[0][1]).toMatch(/rm -rf instance \.curio/);
    });
});

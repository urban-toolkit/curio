/**
 * Both stacks serve on 16 backend processes behind nginx (--backend-processes)
 * for a release whose launcher has the flag, which each job detects as it
 * detects --guest-packages. The boot timeline shows the launcher's
 * [backend-group] lines, and once the stack is up the home process's /monitor
 * must name every process as answering and none missing, or the deploy fails.
 * The files are read as text, as deployMediaCacheFile.test.ts reads deploy.yml.
 */
import { read } from "./_support/workflowPaths";

const text = read(".github/workflows/deploy.yml");
const jobs = text.split(/^ {2}deploy-(?:dev|stable):$/m).slice(1);
/** Each stack's Compose project and its job's text. */
const STACKS: Array<[string, string]> = [
    ["curio-dev", jobs[0] ?? ""],
    ["curio", jobs[1] ?? ""],
];
const PROCESSES = 16;

const escape = (literal: string): string => literal.replace(/[.*+?^${}()|[\]\\/]/g, "\\$&");

/** Where `needle` is in `haystack`, which must hold it once. */
function once(haystack: string, needle: string): number {
    const first = haystack.indexOf(needle);
    expect(first).toBeGreaterThan(-1);
    expect(haystack.indexOf(needle, first + 1)).toBe(-1);
    return first;
}

describe("The deploy's backend processes", () => {
    test("the two jobs are dev's and stable's", () => {
        expect(jobs).toHaveLength(2);
        expect(STACKS[0][1]).toContain("\n          cd /srv/curio-dev\n");
        expect(STACKS[1][1]).toContain("\n          cd /srv/curio\n");
    });

    test("each stack names 16, only for a launcher that declares the flag", () => {
        expect(read("utk_curio/main.py")).toMatch(/add_argument\(\s*"--backend-processes"/);
        const args = `processes_args=", \\"--backend-processes\\", \\"$backend_processes\\""`;
        for (const [, job] of STACKS) {
            const detect = new RegExp(
                `^( +)if grep -q -e '"--backend-processes"' utk_curio\\/main\\.py; then\\n\\1 {2}backend_processes=${PROCESSES}\\n\\1 {2}${escape(args)}\\n\\1fi$`,
                "gm",
            );
            expect(job.match(detect)).toHaveLength(1);
            const flag = job.indexOf(`grep -q -e '"--backend-processes"'`);
            expect(once(job, 'backend_processes=""')).toBeLessThan(flag);
            expect(once(job, 'processes_args=""')).toBeLessThan(flag);
        }
    });

    test("each stack's command line names them last, after setting them", () => {
        for (const [, job] of STACKS) {
            const command = job.search(/printf ' {4}command: \[[^\n]* "\$processes_args" >> docker-compose\.site\.yml\n/);
            expect(command).toBeGreaterThan(-1);
            expect(job.indexOf(`grep -q -e '"--backend-processes"'`)).toBeLessThan(command);
        }
    });

    test("each stack's boot timeline shows the launcher's backend-group lines", () => {
        expect(read("utk_curio/cli/backend_group.py")).toMatch(/log_info\(f"\[backend-group\] /);
        for (const [, job] of STACKS) {
            const lines = job.slice(once(job, 'echo "=== boot timeline ==="')).split("\n");
            expect(lines[2]).toMatch(/^ +\| grep -E "/);
            expect(lines[2]).toContain("|\\[backend-group\\]|");
        }
    });

    test("once each stack is up, the deploy fails unless /monitor names every process answering and none missing", () => {
        // The home process's answer the check reads.
        expect(read("utk_curio/backend/app/monitor/processes.py")).toMatch(
            /return \{"count": self\.count, "answered": [^\n]*, "missing": [^\n]*\}/,
        );
        expect(read("utk_curio/backend/app/monitor/routes.py")).toContain('payload["backendProcesses"] = ');
        for (const [project, job] of STACKS) {
            const block = /^( +)if \[ -n "\$processes_args" \]; then\n\1 {2}echo "=== backend processes ==="\n[\s\S]*?\n\1fi$/m.exec(job);
            expect(block).not.toBeNull();
            const check = block?.[0] ?? "";
            expect(job.indexOf(check)).toBeGreaterThan(once(job, 'echo "=== waiting for health ==="'));
            expect(check).toContain(`docker compose -p ${project} exec -T curio \\\n`);
            expect(check).toContain('urlopen("http://127.0.0.1:5002/api/monitor", timeout=30)).get("backendProcesses")');
            expect(check).toContain('print(p.get("count"), len(p.get("answered") or []), len(p.get("missing") or []))');
            expect(check).toContain("< /dev/null");
            expect(check).toContain('if [ "$processes_line" = "$backend_processes $backend_processes 0" ]; then');
            expect(check).toMatch(/if \[ "\$SECONDS" -ge "\$deadline" \]; then\n[^\n]*::error::[^\n]*\n[^\n]*\n +exit 1\n/);
        }
    });
});

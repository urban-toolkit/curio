/**
 * Each hosted stack, dev and stable, publishes its ports on 127.0.0.1 alone
 * and lets Curio hold 65536 open files, soft and hard. Each deploy job writes
 * that into its own docker-compose.site.yml, the last file its COMPOSE_FILE
 * names, whose ports replace docker-compose.yml's (`!override`), which publish
 * 5002 and 8080 on every interface. Each job's site file is read from its own
 * heredoc in deploy.yml, as deployBackendProcesses.test.ts reads that file,
 * so one stack's ports and limits are checked apart from the other's.
 */
import { read } from "./_support/workflowPaths";

const text = read(".github/workflows/deploy.yml");
const jobs = text.split(/^ {2}deploy-(?:dev|stable):$/m).slice(1);
/** Each stack's name and its job's text. */
const STACKS: Array<[string, string]> = [
    ["dev", jobs[0] ?? ""],
    ["stable", jobs[1] ?? ""],
];
const OPEN_FILES = 65536;
/** A port Docker publishes on 127.0.0.1 alone: the host port a number or a
 * variable with a number for its default, as stable writes it. */
const LOOPBACK = /^127\.0\.0\.1:(?:\d+|\$\{[A-Z][A-Z0-9_]*:-\d+\}):\d+(?:\/(?:tcp|udp))?$/;
const HEREDOC = /cat > "\$site" <<'SITE'\n([\s\S]*?)\n *SITE\n/g;

/** What a job's docker-compose.site.yml says of its curio service. */
interface Site {
    /** The ports it publishes, as written; null when it names none. */
    ports: string[] | null;
    /** Whether they replace docker-compose.yml's ports rather than join them. */
    override: boolean;
    /** Its open-files limit; null when it sets none. */
    nofile: { soft: number; hard: number } | null;
}

/** The text of the one docker-compose.site.yml heredoc in *job*. */
function siteBlock(job: string): string {
    const found = [...job.matchAll(HEREDOC)];
    expect(found).toHaveLength(1);
    return found[0][1];
}

/** Each key of a block of YAML mappings by its dotted path, with the text after
 * its colon, and each block sequence's items by its key's path. */
function flatten(block: string): { values: Map<string, string>; items: Map<string, string[]> } {
    const values = new Map<string, string>();
    const items = new Map<string, string[]>();
    const open: Array<{ indent: number; key: string }> = [];
    for (const line of block.split("\n")) {
        const content = line.trim();
        if (content === "" || content.startsWith("#")) continue;
        const indent = line.length - line.trimStart().length;
        while (open.length > 0 && open[open.length - 1].indent >= indent) open.pop();
        const parent = open.map((entry) => entry.key).join(".");
        if (content.startsWith("- ")) {
            items.set(parent, [...(items.get(parent) ?? []), content.slice(2).trim()]);
            continue;
        }
        const entry = /^([A-Za-z_][\w-]*):(?:\s+(.*))?$/.exec(content);
        if (entry === null) throw new Error(`docker-compose.site.yml holds a line of no key: ${JSON.stringify(line)}`);
        values.set(parent ? `${parent}.${entry[1]}` : entry[1], entry[2] ?? "");
        open.push({ indent, key: entry[1] });
    }
    return { values, items };
}

function unquoted(scalar: string): string {
    const found = /^(["'])(.*)\1$/.exec(scalar.trim());
    return found ? found[2] : scalar.trim();
}

/** The curio service of the site file *block* holds. */
function siteOf(block: string): Site {
    const { values, items } = flatten(block);
    let ports: string[] | null = null;
    let override = false;
    const written = values.get("services.curio.ports");
    if (written !== undefined) {
        let rest = written;
        const tag = /^!(\w+)\s*/.exec(rest);
        if (tag) {
            override = tag[1] === "override";
            rest = rest.slice(tag[0].length);
        }
        if (rest.startsWith("[") && rest.endsWith("]")) {
            ports = rest.slice(1, -1).split(",").map(unquoted).filter((port) => port !== "");
        } else if (rest === "") {
            ports = (items.get("services.curio.ports") ?? []).map(unquoted);
        }
    }
    const limit = values.get("services.curio.ulimits.nofile");
    let nofile: Site["nofile"] = null;
    if (limit !== undefined && /^\d+$/.test(limit)) {
        nofile = { soft: Number(limit), hard: Number(limit) };
    } else if (limit !== undefined) {
        const soft = /\bsoft:\s*(\d+)/.exec(limit)?.[1] ?? values.get("services.curio.ulimits.nofile.soft");
        const hard = /\bhard:\s*(\d+)/.exec(limit)?.[1] ?? values.get("services.curio.ulimits.nofile.hard");
        if (soft !== undefined && hard !== undefined) nofile = { soft: Number(soft), hard: Number(hard) };
    }
    return { ports, override, nofile };
}

/** Each way *site* leaves a port reachable past 127.0.0.1, or Curio's open
 * files at another limit than 65536; none when it does neither. */
function siteProblems(site: Site): string[] {
    const problems: string[] = [];
    if (site.ports === null || site.ports.length === 0) {
        problems.push("publishes no ports of its own, so docker-compose.yml's publish 5002 and 8080 on every interface");
    } else {
        if (!site.override) problems.push("adds its ports to docker-compose.yml's, which publish 5002 and 8080 on every interface, where !override replaces them");
        for (const port of site.ports) {
            if (!LOOPBACK.test(port)) problems.push(`publishes ${port}, which is not on 127.0.0.1 alone`);
        }
    }
    if (site.nofile === null) problems.push("sets no open-files limit, ulimits.nofile");
    else if (site.nofile.soft !== OPEN_FILES || site.nofile.hard !== OPEN_FILES) {
        problems.push(`sets open files to soft ${site.nofile.soft} and hard ${site.nofile.hard}, not ${OPEN_FILES}`);
    }
    return problems;
}

/** The port's container side: what it publishes. */
const containerPort = (port: string): string => port.replace(/\/(?:tcp|udp)$/, "").split(":").pop() ?? "";

describe("Each hosted stack's ports and open files", () => {
    test("the two jobs are dev's and stable's", () => {
        expect(jobs).toHaveLength(2);
        expect(STACKS[0][1]).toContain("\n          cd /srv/curio-dev\n");
        expect(STACKS[1][1]).toContain("\n          cd /srv/curio\n");
    });

    test.each(STACKS)("%s publishes 5002 and 8080 on 127.0.0.1 alone and allows 65536 open files", (_stack, job) => {
        const site = siteOf(siteBlock(job));
        expect(siteProblems(site)).toEqual([]);
        expect((site.ports ?? []).map(containerPort).sort()).toEqual(["5002", "8080"]);
    });

    test.each(STACKS)("%s's compose files end with that site file", (_stack, job) => {
        const written = job.search(HEREDOC);
        const exports = [...job.matchAll(/^ *export COMPOSE_FILE=(.*)$/gm)];
        expect(written).toBeGreaterThan(-1);
        expect(exports[0]?.[1]).toBe("$compose_dir/docker-compose.yml:$compose_dir/docker-compose.deploy.yml");
        const last = exports[exports.length - 1];
        expect(last?.[1]).toBe("$COMPOSE_FILE:$site");
        expect(last?.index ?? -1).toBeGreaterThan(written);
    });
});

/** *job* with *plant* made to its site file's text. */
function planted(job: string, plant: (block: string, firstPort: string) => string): string {
    const block = siteBlock(job);
    const firstPort = (siteOf(block).ports ?? [""])[0];
    const changed = plant(block, firstPort);
    expect(changed).not.toBe(block);
    return job.replace(block, changed);
}

/** Each break of the rule planted in a stack's site file, and the words of
 * the problem it raises. */
const PLANTS: Array<[string, (block: string, firstPort: string) => string, string]> = [
    [
        "a port with no host address, on every interface",
        (block, port) => block.replace(`"${port}"`, `"${port.replace(/^127\.0\.0\.1:/, "")}"`),
        "which is not on 127.0.0.1 alone",
    ],
    [
        "a port on 0.0.0.0",
        (block, port) => block.replace(`"${port}"`, `"${port.replace(/^127\.0\.0\.1:/, "0.0.0.0:")}"`),
        "which is not on 127.0.0.1 alone",
    ],
    [
        "no ulimits",
        (block) => block.replace(/\n *ulimits:\n *nofile: \{[^}\n]*\}/, ""),
        "sets no open-files limit",
    ],
    [
        "ports joined to docker-compose.yml's",
        (block) => block.replace("ports: !override [", "ports: ["),
        "where !override replaces them",
    ],
    [
        "a lower soft limit",
        (block) => block.replace(/nofile: \{soft: \d+,/, "nofile: {soft: 1024,"),
        `not ${OPEN_FILES}`,
    ],
];

describe("The check refuses a stack's site file planted with", () => {
    const cases = STACKS.flatMap(([stack, job]) => PLANTS.map(([what, plant, words]) => [what, stack, job, plant, words] as const));

    test.each(cases)("%s, in %s's", (_what, _stack, job, plant, words) => {
        expect(siteProblems(siteOf(siteBlock(job)))).toEqual([]);
        const problems = siteProblems(siteOf(siteBlock(planted(job, plant))));
        expect(problems.some((problem) => problem.includes(words))).toBe(true);
    });
});

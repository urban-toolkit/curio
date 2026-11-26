/**
 * Every container that starts Curio's frontend asks for it on every interface.
 *
 * The launcher's frontend listens on --frontend-host (default localhost), as
 * the backend listens on --backend-host, so that a local start serves the
 * canvas to this machine alone. Inside a container, the port Docker publishes
 * reaches only a server on the container's own network address, so each
 * container command passes --frontend-host 0.0.0.0, as it passes
 * --backend-host 0.0.0.0. The commands are found, not listed: the Dockerfile's
 * CMD and each command or entrypoint of a file in docker/ that runs
 * `curio.py start` for a frontend (`all` or `frontend`).
 */
import * as fs from "fs";
import * as path from "path";

import { REPO_ROOT, read } from "./_support/workflowPaths";

/** The words of a YAML key's value: a flow list, a block list of words, or the
 * folded text of `sh -c`, with each word's quotes taken off. */
function words(lines: string[], start: number): string[] {
    const indent = lines[start].length - lines[start].trimStart().length;
    const inline = lines[start].slice(lines[start].indexOf(":") + 1).trim();
    const body: string[] = [];
    for (const line of lines.slice(start + 1)) {
        if (line.trim() !== "" && line.length - line.trimStart().length <= indent) break;
        const text = line.trim();
        if (text === "" || text.startsWith("#")) continue;
        body.push(text.startsWith("- ") ? text.slice(2) : text);
    }
    const text = inline.startsWith("[") ? inline.slice(1, -1).replace(/,/g, " ") : [inline, ...body].join(" ");
    return text
        .split(/\s+/)
        .map((word) => word.replace(/^["']|["']$/g, ""))
        .filter((word) => word !== "" && word !== ">-" && word !== "|");
}

/** The compose files whose command or entrypoint this test read curio.py in. */
const READ = new Set<string>();

/** Each launcher start that runs a frontend, as `[where, its words]`. */
function frontendStarts(): Array<[string, string[]]> {
    const starts: Array<[string, string[]]> = [];
    const keep = (where: string, said: string[]) => {
        if (said.some((word) => /curio\.py$/.test(word))) READ.add(where.replace(/:\d+$/, ""));
        const at = said.findIndex((word, i) => /curio\.py$/.test(word) && said[i + 1] === "start");
        if (at < 0) return;
        const server = said[at + 2];
        if (server === undefined || server.startsWith("-") || server === "all" || server === "frontend") {
            starts.push([where, said.slice(at)]);
        }
    };

    const dockerfile = read("docker/Dockerfile");
    for (const cmd of dockerfile.match(/^CMD (\[.*\])$/gm) ?? []) {
        keep("docker/Dockerfile CMD", JSON.parse(cmd.slice(4)));
    }
    const compose = fs.readdirSync(path.join(REPO_ROOT, "docker")).filter((name) => name.endsWith(".yml")).sort();
    for (const name of compose) {
        const lines = read(`docker/${name}`).split("\n");
        lines.forEach((line, i) => {
            if (/^\s+(command|entrypoint):/.test(line)) keep(`docker/${name}:${i + 1}`, words(lines, i));
        });
    }
    return starts;
}

const STARTS = frontendStarts();

test("the Dockerfile and each compose file that starts a frontend are found", () => {
    const where = STARTS.map(([place]) => place.replace(/:\d+$/, ""));
    expect(where).toEqual(expect.arrayContaining([
        "docker/Dockerfile CMD",
        "docker/docker-compose.deploy.yml",
        "docker/docker-compose.ci.yml",
        "docker/docker-compose.ci-isolated.yml",
        "docker/docker-compose.ci-exec-user.yml",
        "docker/docker-compose.ci-stress.yml",
    ]));
});

test("every compose file that runs curio.py is read, in whatever layout it writes its command", () => {
    // A layout words() cannot read would leave its start out of the checks
    // below, which would then pass without it.
    const naming = fs.readdirSync(path.join(REPO_ROOT, "docker"))
        .filter((name) => name.endsWith(".yml"))
        .filter((name) => read(`docker/${name}`).split("\n").some((line) => {
            const code = line.replace(/#.*$/, "");
            return /curio\.py/.test(code);
        }))
        .map((name) => `docker/${name}`);
    expect(naming.length).toBeGreaterThan(0);
    expect([...READ].sort()).toEqual(expect.arrayContaining(naming));
});

test.each(STARTS)("%s asks for the frontend on every interface", (_where, said) => {
    const at = said.indexOf("--frontend-host");
    expect(at).toBeGreaterThan(-1);
    expect(said[at + 1]).toBe("0.0.0.0");
});

test.each(STARTS)("%s also asks for the backend on every interface, as before", (_where, said) => {
    expect(said[said.indexOf("--backend-host") + 1]).toBe("0.0.0.0");
});

/**
 * Does the Agent Catalog guide list Curio's skills, and each agent's, as they are?
 *
 * docs/AGENT-CATALOG.md lists every skill Curio ships in its table of skills,
 * and the skills each agent's manifest names in its table of each agent's
 * skills. Both are held here to `skills/` and to the manifests in `agents/`,
 * so a skill added, renamed, moved out of the preamble or given to another
 * agent fails until the guide says so. Both tables of agents have a Skills
 * column, each of the guide's four words is defined once, and the guide never
 * says job. The backend's tests run in an image without the guides, so this
 * check is Jest's, on the checkout.
 */
import * as fs from "fs";
import * as path from "path";

import { REPO_ROOT, read } from "../_support/workflowPaths";

const GUIDE = "docs/AGENT-CATALOG.md";
const SKILLS_TABLE = "| Skill | It tells an agent how to | It serves |";
const AGENTS_TABLE = "| Agent | Skills | Its modes are handed |";

interface AgentManifest {
    name: string;
    kind?: string;
    skills?: string[];
}

/** The rows of the table whose header line is *header*, each as its cells. */
function tableRows(doc: string, header: string): string[][] {
    const lines = doc.split("\n");
    const start = lines.indexOf(header);
    if (start < 0) throw new Error(`${GUIDE} has no table headed ${header}`);
    const rows: string[][] = [];
    for (const line of lines.slice(start + 2)) {
        if (!line.startsWith("|")) break;
        rows.push(line.slice(1, -1).split("|").map((cell) => cell.trim()));
    }
    return rows;
}

/** Every name a cell gives in backticks, in its order. */
function codeNames(cell: string): string[] {
    return Array.from(cell.matchAll(/`([^`]+)`/g), (match) => match[1]);
}

/** Each folder of `skills/` that holds a `SKILL.md`, sorted. */
function shippedSkills(): string[] {
    const root = path.join(REPO_ROOT, "skills");
    return fs.readdirSync(root)
        .filter((name) => fs.existsSync(path.join(root, name, "SKILL.md")))
        .sort();
}

/** The manifest of each agent Curio ships, the base entry left out. */
function agentManifests(): AgentManifest[] {
    const root = path.join(REPO_ROOT, "agents");
    return fs.readdirSync(root)
        .filter((folder) => fs.existsSync(path.join(root, folder, "manifest.json")))
        .map((folder) => JSON.parse(read(path.join("agents", folder, "manifest.json"))) as AgentManifest)
        .filter((manifest) => manifest.kind !== "base");
}

const doc = read(GUIDE);

test("the guide's table of skills lists every skill Curio ships, once", () => {
    const listed = tableRows(doc, SKILLS_TABLE).map((row) => codeNames(row[0])[0]);
    expect(shippedSkills()).toHaveLength(16);
    expect(new Set(listed).size).toBe(listed.length);
    expect([...listed].sort()).toEqual(shippedSkills());
});

test("the skills the guide puts in the preamble are the ones the preamble places", () => {
    const inThePreamble = tableRows(doc, SKILLS_TABLE)
        .filter((row) => row[2].includes("in the preamble"))
        .map((row) => codeNames(row[0])[0]);
    const preamble = read("agents/agent.curio.builtin@1/default_preamble.md");
    const placed = Array.from(preamble.matchAll(/\{\{skill:([^{}]+)\}\}/g), (match) => match[1]);
    expect(placed).toHaveLength(3);
    expect([...inThePreamble].sort()).toEqual([...placed].sort());
});

test("the guide's table of each agent's skills is each manifest's skills, in its order", () => {
    const named = new Map(agentManifests().map((manifest) => [manifest.name, manifest.skills ?? []]));
    expect(named.size).toBe(7);
    const listed = new Map(tableRows(doc, AGENTS_TABLE).map((row) => [row[0].replace(/\*\*/g, ""), codeNames(row[1])]));
    expect([...listed.keys()].sort()).toEqual([...named.keys()].sort());
    for (const [agent, skills] of named) {
        expect({ agent, skills: listed.get(agent) }).toEqual({ agent, skills });
    }
});

test("both tables of agents have a Skills column", () => {
    for (const start of ["| Agent | In chat |", "| Helper |"]) {
        const header = doc.split("\n").find((line) => line.startsWith(start));
        expect(header).toBeDefined();
        expect((header ?? "").split("|").map((cell) => cell.trim())).toContain("Skills");
    }
});

test("the guide defines each of its four words once and never says job", () => {
    for (const word of ["In chat", "Tools", "Modes", "Skills"]) {
        expect({ word, definitions: doc.split(`- **${word}:**`).length - 1 }).toEqual({ word, definitions: 1 });
    }
    // The skill's definition, in the words of agentskills.io, is said once.
    expect(doc.split("tells an agent how to do a specific task").length - 1).toBe(1);
    expect(doc).not.toMatch(/\bjobs?\b/i);
});

/**
 * Does the Skill Catalog guide list Curio's skills as they are, and do the
 * guides that send a reader to it link it?
 *
 * docs/SKILL-CATALOG.md lists every skill Curio ships in its table of skills,
 * held here to `skills/` and to the skills the shared preamble places, so a
 * skill added, renamed or moved out of the preamble fails until the guide says
 * so. The guide never says job, and the docs index, the README, the Agent
 * Catalog guide and USAGE link it. Each agent's skills are
 * docs/AGENT-CATALOG.md's, which agentCatalogSkillsDocs.test.ts holds to the
 * manifests. The backend's tests run in an image without the guides, so this
 * check is Jest's, on the checkout.
 */
import * as fs from "fs";
import * as path from "path";

import { REPO_ROOT, read } from "../_support/workflowPaths";

const GUIDE = "docs/SKILL-CATALOG.md";
const SKILLS_TABLE = "| Skill | It tells an agent how to | It serves |";

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

const doc = read(GUIDE);

test("the guide's table of skills lists every skill Curio ships, once", () => {
    const listed = tableRows(doc, SKILLS_TABLE).map((row) => codeNames(row[0])[0]);
    expect(shippedSkills()).toHaveLength(21);
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

test("the guide never says job", () => {
    expect(doc).not.toMatch(/\bjobs?\b/i);
});

test("the docs index, the README, the Agent Catalog guide and USAGE link it", () => {
    for (const name of ["docs/README.md", "docs/AGENT-CATALOG.md", "docs/USAGE.md"]) {
        expect({ name, links: read(name).includes("](SKILL-CATALOG.md") }).toEqual({ name, links: true });
    }
    expect(read("README.md")).toContain("](docs/SKILL-CATALOG.md");
});

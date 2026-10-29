/**
 * The skill words and the `/` command the chat and the Agent Catalog share
 * (`services/agents/agentSkills.ts`).
 *
 * Every feature of a dataflow a skill Curio ships can serve has words for its
 * details: the features are read from each `skills/<name>/SKILL.md`'s
 * `curio-features`, so a skill that names a new one fails here until the words
 * are written.
 */
import * as fs from "fs";
import * as path from "path";

import {
  SKILL_FEATURE_WORDS,
  SKILL_NAME_MAX,
  skillByline,
  skillServes,
  skillsMatching,
  skillsUsedBy,
  slashQuery,
  suggestSkillName,
  withSlashCommand,
} from "../../services/agents/agentSkills";
import { skillUploadForm } from "../../services/agents/skillsApi";
import { REPO_ROOT } from "../_support/workflowPaths";

describe("the skills a reply's run used", () => {
  it("lists those it was handed, named, kept and loaded, each once, in that order", () => {
    expect(
      skillsUsedBy({
        executionId: "e1",
        usage: null,
        status: "ok",
        pins: { skills: { catalog: ["a", "b", "c", "d"], kept: ["c"], named: ["b"], handed: ["a"] } },
        skillsLoaded: ["d", "a"],
      }),
    ).toEqual([
      { name: "a", use: "handed" },
      { name: "b", use: "named" },
      { name: "c", use: "kept" },
      { name: "d", use: "loaded" },
    ]);
  });

  it("lists none for a run that held only a catalog, or predates the record's skills", () => {
    expect(skillsUsedBy({ executionId: "e1", usage: null, status: "ok", pins: { skills: { catalog: ["a"] } } })).toEqual([]);
    expect(skillsUsedBy({ executionId: "e1", usage: null, status: "ok" })).toEqual([]);
    expect(skillsUsedBy(undefined)).toEqual([]);
  });
});

describe("the / command", () => {
  it("is the first word while the caret is in it", () => {
    expect(slashQuery("/", 1)).toBe("");
    expect(slashQuery("/map", 4)).toBe("map");
    expect(slashQuery("/map-edits move the river", 2)).toBe("map-edits");
    expect(slashQuery("/map-edits move the river", 20)).toBeNull();
    expect(slashQuery("move /map-edits", 15)).toBeNull();
    expect(slashQuery("", 0)).toBeNull();
  });

  it("puts /<name> and a space in place of the first word, keeping the rest", () => {
    expect(withSlashCommand("/", "widgets")).toBe("/widgets ");
    expect(withSlashCommand("/wid", "widgets")).toBe("/widgets ");
    expect(withSlashCommand("/wid   remove the towers", "widgets")).toBe("/widgets remove the towers");
  });

  it("matches names that start with what was typed first, then names that hold it", () => {
    const skills = [{ name: "map-edits" }, { name: "autark-starter" }, { name: "autark" }];
    expect(skillsMatching(skills, "aut").map((s) => s.name)).toEqual(["autark-starter", "autark"]);
    expect(skillsMatching(skills, "start").map((s) => s.name)).toEqual(["autark-starter"]);
    expect(skillsMatching(skills, "").map((s) => s.name)).toEqual(["map-edits", "autark-starter", "autark"]);
  });
});

describe("what a skill serves", () => {
  it("names its kinds of node, then its features in plain words", () => {
    expect(skillServes({ nodeKinds: ["Data Pool"], features: ["interaction-edges"] })).toEqual([
      "Data Pool",
      "Dataflows with interaction edges",
    ]);
  });

  it("has words for every feature a skill Curio ships names", () => {
    const root = path.join(REPO_ROOT, "skills");
    const named = new Set<string>();
    for (const folder of fs.readdirSync(root)) {
      const file = path.join(root, folder, "SKILL.md");
      if (!fs.existsSync(file)) continue;
      const line = fs.readFileSync(file, "utf8").split("\n").find((text) => /^\s+curio-features:/.test(text));
      for (const feature of (line ?? "").replace(/^\s+curio-features:/, "").trim().split(/\s+/)) {
        if (feature) named.add(feature);
      }
    }
    expect(named.size).toBeGreaterThan(0);
    expect([...named].filter((feature) => !(feature in SKILL_FEATURE_WORDS))).toEqual([]);
  });
});

describe("whose a skill is", () => {
  it("names the author its metadata gives, else whose it is, never Curio for an account's", () => {
    expect(skillByline({ author: "parks-team", source: "yours" })).toBe("parks-team");
    expect(skillByline({ author: null, source: "yours" })).toBe("you");
    expect(skillByline({ source: "shared" })).toBe("shared catalog");
    expect(skillByline({ author: "curio", source: "curio" })).toBe("curio");
    expect(skillByline({})).toBe("curio");
  });
});

describe("the name an import review offers", () => {
  it("is the name given in a skill name's letters, with -2 when that is the name refused", () => {
    expect(suggestSkillName({ name: "Street Trees", givenName: "Street Trees" })).toBe("street-trees");
    expect(suggestSkillName({ name: "widgets", givenName: "widgets" })).toBe("widgets-2");
    expect(suggestSkillName({ name: "pdf_tools", givenName: "pdf_tools" })).toBe("pdf-tools");
    expect(suggestSkillName({ name: "--", givenName: "--" })).toBe("skill");
    const long = suggestSkillName({ name: "a".repeat(62), givenName: "a".repeat(80) });
    expect(long).toBe(`${"a".repeat(62)}-2`);
    expect(long.length).toBeLessThanOrEqual(SKILL_NAME_MAX);
  });
});

describe("a skill's upload", () => {
  it("sends each file with its path in what was picked, and the name and agents asked for", () => {
    const form = skillUploadForm(
      [
        { path: "street-trees/SKILL.md", file: new Blob(["---"]) },
        { path: "street-trees/references/species.md", file: new Blob(["Oak"]) },
      ],
      { name: "my-trees", agents: ["agent.curio.dataset-finder@1"] },
    );
    const files = form.getAll("files") as File[];
    expect(files.map((file) => file.name)).toEqual(["SKILL.md", "species.md"]);
    expect(JSON.parse(form.get("paths") as string)).toEqual([
      "street-trees/SKILL.md",
      "street-trees/references/species.md",
    ]);
    expect(form.get("name")).toBe("my-trees");
    expect(JSON.parse(form.get("agents") as string)).toEqual(["agent.curio.dataset-finder@1"]);
  });

  it("sends no name and no agents when the review asked for neither", () => {
    const form = skillUploadForm([{ path: "SKILL.md", file: new Blob(["---"]) }]);
    expect(form.get("name")).toBeNull();
    expect(form.get("agents")).toBeNull();
  });
});

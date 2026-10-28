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
  skillServes,
  skillsMatching,
  skillsUsedBy,
  slashQuery,
  withSlashCommand,
} from "../../services/agents/agentSkills";
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

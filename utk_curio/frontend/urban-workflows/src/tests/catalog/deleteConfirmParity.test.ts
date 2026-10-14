/**
 * The two permanent deletions in the app ask the same question (#285).
 *
 * Removing Archive (#261) renamed the projects list's destructive action from
 * "Delete forever" to plain "Delete", and the Data Catalog followed - but only
 * on the button. The dialogs still disagreed: projects asked
 * ``Permanently delete "X"?`` while a dataset asked ``Delete X?``, so the word
 * that carries the permanence appeared on one surface and not the other, for
 * the same act.
 *
 * The permanence claim belongs in the dialog rather than on the button, which
 * is what #285 settled. This pins both halves of that: the title says
 * "permanently", and the body qualifies the claim with the one sentence
 * `retentionCopy` exists to keep honest - the platform controls its own live
 * store and cannot speak for an operator's backups.
 *
 * Read from disk: both confirmations are assembled inside larger components
 * (a page and a drawer hook), and what matters is the copy each one hands the
 * dialog, not the tree around it.
 */
import fs from "fs";
import path from "path";

import { permanentDeletionNotice } from "../../services/retentionCopy";

const SRC = path.resolve(__dirname, "../..");
const read = (rel: string) => fs.readFileSync(path.join(SRC, rel), "utf8");

const PROJECTS = "pages/projects/ProjectsList.tsx";
const DATASETS = "components/datasets/catalog/useDatasetCatalogDrawer.ts";

/** Every .ts and .tsx file under *rel*. */
function sources(rel: string): string[] {
  const dir = path.join(SRC, rel);
  const out: string[] = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...sources(path.relative(SRC, full)));
    else if (/\.tsx?$/.test(entry.name)) out.push(path.relative(SRC, full));
  }
  return out;
}

describe("permanent deletion confirmations", () => {
  test("both ask to permanently delete, by name and in quotes", () => {
    expect(read(PROJECTS)).toContain('title={`Permanently delete "${deleteTarget.name}"?`}');
    expect(read(DATASETS)).toContain('title: `Permanently delete "${title}"?`');
  });

  test("a model is not one of them: it leaves the account as a package does", () => {
    // The Model Catalog is the Node Catalog's code over model packages, so a
    // model is removed from a dataflow (and from the account with the last
    // one), never deleted outright by a question of its own.
    expect(fs.existsSync(path.join(SRC, "components/models/catalog/useModelDelete.ts"))).toBe(false);
    for (const rel of [...sources("components/models"), ...sources("pages/models")]) {
      expect(read(rel)).not.toContain("Permanently delete");
      expect(read(rel)).not.toContain("permanentDeletionNotice");
    }
  });

  test("neither repeats the word on its button", () => {
    // "Delete forever" earned its keep only while Archive sat beside it as the
    // softer-sounding option. With the title stating the permanence, the verb
    // carries the button.
    for (const rel of [PROJECTS, DATASETS]) {
      expect(read(rel)).not.toContain("Delete forever");
    }
    expect(read(PROJECTS)).toContain('confirmLabel="Delete"');
    expect(read(DATASETS)).toContain('confirmLabel: "Delete"');
  });

  test("both bodies carry the shared retention sentence", () => {
    // A title claiming permanence has to be qualified in the same breath, and
    // `permanentDeletionNotice` is where that qualification is written once.
    for (const rel of [PROJECTS, DATASETS]) {
      expect(read(rel)).toContain("permanentDeletionNotice()");
    }
  });

  test("that sentence still scopes the claim to this deployment", () => {
    // Guards the copy itself, not just the call: the dialogs now assert
    // permanence, so the sentence under them must keep saying what the
    // platform can and cannot know.
    const notice = permanentDeletionNotice();
    expect(notice).toContain("live store");
    expect(notice).toContain("backup");
  });

  test("the dataset dialog still states its wider blast radius", () => {
    // A dataset delete reaches dataflows the user is not looking at. The
    // shared sentence is added to that warning, not in place of it.
    const src = read(DATASETS);
    expect(src).toContain("every dataflow");
    expect(src).toContain("not just this one");
  });
});

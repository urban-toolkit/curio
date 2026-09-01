/**
 * The three catalog drawers do not repeat themselves.
 *
 * The user's stated principle: **the default should be no repetition.** Two
 * things violated it, and in both cases the Agent drawer was the one that had
 * it right, so the other two were brought into line rather than the reverse.
 *
 * 1. The Data and Node drawers printed the ACTIVE TAB'S OWN LABEL again, as a
 *    section heading directly beneath the tab strip - so "Browse all" appeared
 *    twice, a few pixels apart, one of them already highlighted as the selected
 *    tab. The heading carried no information the tab strip was not already
 *    showing.
 *
 * 2. All three showed an "This dataflow isn't saved yet; adding will save it
 *    first" banner while `projectId` was null. It is gone: the add now states
 *    what it will do in its confirmation dialog, and the save indicator shows
 *    that it happened, so the banner was a third telling of the same thing -
 *    and one that appeared on some screens and not others depending on whether
 *    the dataflow happened to be saved.
 *
 * Read from disk, the established pattern for this kind of claim: CSS modules
 * resolve through `identity-obj-proxy` under jest, so a render assertion cannot
 * distinguish a heading that is present from one that is not styled.
 */
import fs from "fs";
import path from "path";

const SRC = path.resolve(__dirname, "../..");
const read = (rel: string) => fs.readFileSync(path.join(SRC, rel), "utf8");

const DRAWERS: [string, string][] = [
  ["data", "components/datasets/catalog/DatasetCatalogDrawer.tsx"],
  ["node", "components/packages/publishing/NodeCatalogDrawer.tsx"],
  ["agent", "components/agents/catalog/AgentCatalogDrawer.tsx"],
];

describe("no catalog repeats its own tab label as a heading", () => {
  test.each(DRAWERS)("the %s drawer prints no tab-label heading", (_kind, file) => {
    const src = read(file);
    // The two shapes it took: `shell.sectionLabel` with the label table piped
    // straight into it.
    expect(src).not.toMatch(/sectionLabel\}>\{TAB_LABEL\[/);
    expect(src).not.toMatch(/sectionLabel\}>\{tabLabel\[/);
    // And no drawer should reach for the shared shell's section-heading style
    // at all — the only headings left are the per-list ones ("Your datasets ·
    // 3 in dataflow"), which say something the tab strip does not.
    expect(src).not.toContain("shell.sectionLabel");
  });

  test("the shared drawer shell no longer ships the dead heading style", () => {
    const css = read("components/packages/publishing/CatalogDrawerShell.module.css");
    expect(css).not.toMatch(/^\.sectionLabel \{/m);
  });

  test("the per-list headings survive — they carry a count, not a repeat", () => {
    // "Your datasets · N in dataflow" is not a restatement of the tab; it adds
    // the count. Removing the tab-label headings must not have taken it too.
    expect(read("components/datasets/catalog/InstalledDatasetsList.tsx")).toContain(
      "in dataflow",
    );
    expect(read("components/packages/publishing/MyPackagesList.tsx")).toContain(
      "in dataflow",
    );
  });
});

describe("the unsaved-dataflow banner is gone from every catalog", () => {
  test.each(DRAWERS)("the %s drawer shows no unsaved notice", (_kind, file) => {
    const src = read(file);
    expect(src).not.toContain("UNSAVED_DATAFLOW_NOTICE");
    expect(src).not.toMatch(/isn.{0,6}t saved yet/i);
    // The banner element it lived in, too — no drawer should reintroduce one
    // through the shared shell.
    expect(src).not.toContain("shell.noticeBanner");
  });

  test("the shared copy constant is deleted, not merely unused", () => {
    // Left in place it would invite a fourth surface to import it back.
    expect(fs.existsSync(path.join(SRC, "constants/catalogCopy.ts"))).toBe(false);
  });

  test("the shared shell's notice surface is gone too", () => {
    const css = read("components/packages/publishing/CatalogDrawerShell.module.css");
    expect(css).not.toMatch(/^\.noticeBanner \{/m);
    expect(css).not.toMatch(/^\.noticeBannerText \{/m);
  });

  test("the Node drawer keeps its OWN restart notice, which is unrelated", () => {
    // `NodeCatalogDrawer.module.css` has a separate `.noticeBanner` for the
    // "restart recommended after a shared-library install" line. That one says
    // something real and must survive.
    const src = read("components/packages/publishing/NodeCatalogDrawer.tsx");
    expect(src).toContain("styles.noticeBanner");
    expect(read("components/packages/publishing/NodeCatalogDrawer.module.css")).toMatch(
      /^\.noticeBanner \{/m,
    );
  });
});

describe("every catalog card root carries its identity attribute", () => {
  // `test_frontend/README.md` tells e2e authors to key on these rather than on
  // display copy, "which has been renamed repeatedly". Two of the six card
  // components did not actually have one, so a browse-page card could only be
  // addressed by its title — which is exactly what the README warns against.
  const CARDS: [string, string, string][] = [
    ["data browse", "pages/dataHub/DataCatalogBrowseCard.tsx", "data-dataset-id"],
    ["agent browse", "pages/agents/AgentCatalogBrowseCard.tsx", "data-agent-coord"],
    ["node browse", "pages/catalog/PackageBrowseCard.tsx", "data-pkg-dir"],
    ["node drawer", "components/packages/publishing/PackageCard.tsx", "data-pkg-dir"],
    ["agent drawer", "components/agents/catalog/AgentCatalogDrawer.tsx", "data-agent-coord"],
  ];

  test.each(CARDS)("the %s card exposes %s", (_kind, file, attr) => {
    expect(read(file)).toContain(attr);
  });
});

describe("the Node catalog offers only tabs that do something", () => {
  // "Featured" and "Updates" were rendered, clickable, and inert: the drawer
  // collapsed both onto "browse" before handing the state to the strip, and
  // its list never depended on `tab`. Updates even carried an accent count, so
  // it advertised work it would not do.
  test("the tab strip is Browse all / In dataflow", () => {
    const src = read("components/packages/publishing/DrawerTabs.tsx");
    expect(src).toContain("Browse all");
    expect(src).toContain("In dataflow");
    expect(src).not.toContain(">Featured<");
    expect(src).not.toContain(">Updates<");
    expect(src).not.toContain("updateCount");
  });

  test("the tab type admits no dead members", () => {
    const src = read("components/packages/publishing/packageTypes.ts");
    expect(src).toContain('export type DrawerTab = "browse" | "installed";');
  });

  test("the drawer no longer collapses two tabs onto a third", () => {
    const src = read("components/packages/publishing/NodeCatalogDrawer.tsx");
    expect(src).not.toContain('tab === "featured"');
    expect(src).not.toContain('tab === "updates"');
    // The per-card "update available" line is computed separately and stays.
    expect(read("components/packages/publishing/MyPackagesList.tsx")).toContain(
      "update available",
    );
  });
});

describe("Escape dismisses every catalog drawer, and every one honours its pin", () => {
  // Escape closed the Node and Agent drawers and did nothing in the Data
  // drawer, which had no handler at all. And the Node drawer ignored its own
  // pin, so Escape discarded a pin the user had just set.
  const ESCAPE_OWNERS: [string, string][] = [
    ["data", "components/datasets/catalog/DatasetCatalogDrawer.tsx"],
    ["node", "components/packages/publishing/NodeCatalogDrawer.tsx"],
    ["agent", "providers/AgentCatalogDrawerProvider.tsx"],
  ];

  test.each(ESCAPE_OWNERS)("the %s drawer closes on Escape", (_kind, file) => {
    expect(read(file)).toMatch(/key === "Escape"/);
  });

  test.each(ESCAPE_OWNERS)("the %s drawer's Escape respects the pin", (_kind, file) => {
    expect(read(file)).toMatch(/key === "Escape" && !pinned/);
  });

  test.each(ESCAPE_OWNERS)("the %s drawer stands down for an open modal", (_kind, file) => {
    // ModalShell registers every dialog; a confirmation on top owns Escape.
    expect(read(file)).toContain("modalStackDepth() > 0");
  });
});

describe("the publish pill says what kind of thing it is publishing", () => {
  // `CatalogPublishPill` defaults to the PACKAGE wording, so any surface that
  // does not override it tells the user the wrong thing. The two canvas
  // dataset surfaces did not: hovering Publish on a dataset offered to
  // "Publish this installed package into the shared catalog (packages/)".
  // Publish is the only deployment-wide write in the product, so the copy
  // describing it has to be true.
  const DATASET_SURFACES = [
    "components/datasets/catalog/DatasetCard.tsx",
    "components/datasets/catalog/InstalledDatasetsList.tsx",
    "pages/dataHub/DataCatalogBrowseCard.tsx",
    "pages/dataHub/DataCatalogBrowseDrawer.tsx",
  ];
  const AGENT_SURFACES = [
    "components/agents/catalog/AgentCatalogDrawer.tsx",
    "pages/agents/AgentCatalogBrowseCard.tsx",
    "pages/agents/AgentCatalogBrowseDrawer.tsx",
  ];

  test.each(DATASET_SURFACES)("%s calls a dataset a dataset", (file) => {
    const src = read(file);
    if (!src.includes("<CatalogPublishPill")) return;
    expect(src).toContain("publishActionTitle");
    expect(src).toMatch(/publishActionTitle="Publish this dataset/);
    expect(src).not.toMatch(/publishActionTitle="[^"]*package/);
  });

  test.each(AGENT_SURFACES)("%s calls an agent an agent", (file) => {
    const src = read(file);
    if (!src.includes("<CatalogPublishPill")) return;
    expect(src).toMatch(/publishActionTitle="Publish this agent/);
  });

  test("the default wording is still the package one, for package surfaces", () => {
    // Package surfaces rely on the default rather than repeating it.
    expect(read("components/packages/CatalogPublishPill.tsx")).toContain(
      "Publish this installed package into the shared catalog (packages/)",
    );
  });
});

describe("the node install note describes the environment it really touches", () => {
  // `services.py` installs through `pip_runner.install_python_deps`, which runs
  // `sys.executable -m pip install` - the interpreter Curio itself runs on,
  // shared by every dataflow and every user of the instance. The note used to
  // say "this project's sandbox interpreter", which is a different thing and
  // would let someone install into a shared environment believing it private.
  test("it does not claim the install is project-scoped", () => {
    const src = read("components/packages/publishing/EnvNote.tsx");
    expect(src).not.toMatch(/this project.{0,3}s sandbox interpreter/);
    expect(src).toMatch(/every dataflow and every user|shares|shared/i);
  });
});

describe("one button vocabulary across the catalogs", () => {
  // Black is an action, white with a border is destructive. Publish was
  // neither: a small blue pill in its own size and colour, which read as a
  // status chip saying the thing was already published.
  //
  // Asserted from source because CSS modules resolve through
  // `identity-obj-proxy` under jest, so a render cannot see which rule applied.
  const CARD_STYLES = "components/packages/publishing/PackageCard.module.css";
  const PILL_STYLES = "components/packages/CatalogPublishPill.module.css";

  /** The body of one CSS rule, by selector. */
  function rule(css: string, selector: string): string {
    const at = css.indexOf(`${selector} {`);
    expect(at).toBeGreaterThan(-1);
    return css.slice(at, css.indexOf("}", at));
  }

  test("the action button is the dark fill", () => {
    expect(rule(read(CARD_STYLES), ".btnInstall")).toContain(
      "background: var(--curio-top-bar-bg)",
    );
  });

  test("the destructive button is the bordered light fill", () => {
    const secondary = rule(read(CARD_STYLES), ".btnSecondary");
    expect(secondary).toContain("background: var(--curio-card-bg)");
    expect(secondary).toContain("border: 1px solid var(--curio-border-strong)");
  });

  test("Publish joins the action vocabulary rather than inventing its own", () => {
    const pill = rule(read(PILL_STYLES), ".pillHub");
    expect(pill).toContain("background: var(--curio-top-bar-bg)");
    expect(pill).toContain("color: var(--curio-text-on-dark)");
    // ...and shares the other card buttons' box, so the column lines up.
    expect(pill).toContain("min-width: 96px");
    expect(pill).toContain("height: 30px");
    expect(pill).toContain("border-radius: var(--curio-radius-md)");
    // The blue it used to be is gone.
    expect(pill).not.toContain("--curio-role-published");
  });

  test("Publish is a plain verb in sentence case", () => {
    const src = read("components/packages/CatalogPublishPill.tsx");
    expect(src).toContain('"Publish"');
    // Uppercase is what made it read as a status chip.
    expect(rule(read(PILL_STYLES), ".pillHub")).not.toContain("text-transform: uppercase");
  });

  test("the main-page catalogs use the same two treatments", () => {
    // The Agent browse drawer used the DARK `.addToPaletteBtn` for both "Add to
    // my account" and "Remove from my account", so two opposite actions were
    // the same black button in the same place.
    const browse = read("pages/catalog/CatalogBrowseLayout.module.css");
    expect(rule(browse, ".addToPaletteBtn")).toContain(
      "background: var(--curio-top-bar-bg)",
    );
    const destructive = rule(browse, ".destructiveBtn");
    expect(destructive).toContain("background: var(--curio-card-bg)");
    expect(destructive).toContain("border: 1px solid var(--curio-border-strong)");
    // Same box, so swapping one for the other does not reflow the panel.
    expect(destructive).toContain("height: 42px");

    const drawer = read("pages/agents/AgentCatalogBrowseDrawer.tsx");
    const at = drawer.indexOf("Remove from my account");
    expect(at).toBeGreaterThan(-1);
    expect(drawer.slice(Math.max(0, at - 300), at)).toContain("destructiveBtn");
  });

  test("Delete comes last on the dataset card", () => {
    // The most final action sits furthest from the first one.
    const src = read("components/datasets/catalog/DatasetCard.tsx");
    const publish = src.indexOf("showPublishPill ?");
    const del = src.indexOf("showDelete ?");
    expect(publish).toBeGreaterThan(-1);
    expect(del).toBeGreaterThan(publish);
  });

  test("the Published state stays quiet, and is not a button", () => {
    const badge = rule(read(PILL_STYLES), ".badgeHub");
    expect(badge).toContain("color: var(--curio-text-muted)");
    expect(badge).toContain("cursor: default");
    // Same box as its neighbours so the column does not jump when it swaps in.
    expect(badge).toContain("min-width: 96px");
    expect(badge).toContain("height: 30px");
  });

  test("the dark rail keeps a light treatment, where a black fill would vanish", () => {
    const dock = rule(read(PILL_STYLES), ".pillDock");
    expect(dock).not.toContain("background: var(--curio-top-bar-bg)");
  });
});

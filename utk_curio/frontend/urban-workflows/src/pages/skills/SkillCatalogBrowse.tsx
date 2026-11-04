/**
 * The account-scope Skill Catalog, the tab after the Agent Catalog.
 *
 * A peer of the other browse pages: the same three-column grid from
 * `CatalogBrowseLayout.module.css`, the same rail (`CatalogRail`), the same
 * header (`CatalogPageHeader`: kind icon + h1 + count, then search and
 * import), the same card grid, right-click menu and right-hand detail drawer.
 *
 * It lists the skills the agents read. A skill is added to an agent, and
 * removed from one, in that agent's details, on the Agent Catalog page or in
 * a project's Agent Catalog drawer. The account's own skills come in through
 * **Import skill**, as its agents come in through the Agent Catalog's
 * **Import agent**, and a skill's drawer removes or publishes one, as an
 * agent's drawer does.
 */
import React, { useEffect, useState } from "react";

import type { SkillCard } from "../../services/agents";
import { packagesApi } from "../../services/packages";
import browseStyles from "../catalog/CatalogBrowseLayout.module.css";
import { SkillCatalogBrowseCard } from "./SkillCatalogBrowseCard";
import { SkillCatalogBrowseDrawer } from "./SkillCatalogBrowseDrawer";
import { useSkillCatalogBrowse, type SkillBrowseFilter } from "./useSkillCatalogBrowse";
import { CatalogHeaderImport } from "../catalog/CatalogHeaderImport";
import { CatalogPageHeader } from "../catalog/CatalogPageHeader";
import { CatalogRail } from "../catalog/CatalogRail";
import { SkillDetailModal } from "../../components/skills/catalog/SkillDetailModal";
import { SkillImportModal } from "../../components/skills/catalog/SkillImportModal";
import { CardContextMenu } from "../../components/catalog/CardContextMenu";
import { skillCardActions, type CatalogCardActionId } from "../../components/catalog/catalogCardActions";

export const SkillCatalogBrowse: React.FC = () => {
  const [drawerSlotOpen, setDrawerSlotOpen] = useState(false);
  const [skillFilter, setSkillFilter] = useState<SkillBrowseFilter>("all");
  const [skillSearch, setSkillSearch] = useState("");
  // Separate from the drawer's selection, as on the Agent Catalog page: on
  // arrival the drawer is already open on the first card, so a View details
  // wired to it would have nothing left to change (#189).
  const [detailSkillName, setDetailSkillName] = useState<string | null>(null);
  const [skillImportOpen, setSkillImportOpen] = useState(false);
  // Right-click. The card reports the event, the grid owns the menu (#285).
  const [skillMenu, setSkillMenu] = useState<{ x: number; y: number; skill: SkillCard } | null>(null);
  // The operator's publish switch, read as the other catalog pages read it.
  const [catalogPublishAllowed, setCatalogPublishAllowed] = useState(false);
  const skillBrowse = useSkillCatalogBrowse(skillSearch, skillFilter);

  useEffect(() => {
    void packagesApi
      .factoryCapabilities()
      .then((cap) => {
        setCatalogPublishAllowed(cap.catalogPublish);
      })
      .catch(() => {
        setCatalogPublishAllowed(false);
      });
  }, []);

  const runSkillAction = (id: CatalogCardActionId, skill: SkillCard) => {
    if (id === "view-details") setDetailSkillName(skill.name);
  };

  // From the unfiltered list on purpose - the modal outlives a filter change.
  const detailSkill = detailSkillName
    ? (skillBrowse.skills.find((s) => s.name === detailSkillName) ?? null)
    : null;

  return (
    <div
      className={[browseStyles.page, drawerSlotOpen ? browseStyles.pageWithDrawer : ""]
        .filter(Boolean)
        .join(" ")}
    >
      <CatalogRail
        ariaLabel="Filter skills"
        all={{
          label: "All skills",
          count: skillBrowse.skills.length,
          active: skillFilter === "all",
          onClick: () => setSkillFilter("all"),
        }}
        sections={[
          {
            key: "skills",
            label: "Skills",
            entries: [
              {
                value: "core",
                label: "Core",
                count: skillBrowse.coreCount,
                active: skillFilter === "core",
                onClick: () => setSkillFilter((prev) => (prev === "core" ? "all" : "core")),
              },
            ],
          },
        ]}
      />

      <main className={browseStyles.browseMain}>
        <CatalogPageHeader
          kind="skill"
          iconTitle="Skill catalog"
          title="Skill Catalog"
          count={skillBrowse.filtered.length}
          intro={
            <>
              Skills in the shared catalog. Each tells an agent how to do a specific task. Add one to
              an agent, or remove one, in that agent&apos;s details; the change reaches the agent in{" "}
              <strong>all your projects</strong>.
            </>
          }
          // Skills are listed by name alone, so there is no order to choose.
          viewTools={null}
        >
          <input
            className={browseStyles.hubSearch}
            type="search"
            placeholder="Search skills…"
            aria-label="Search skills"
            value={skillSearch}
            onChange={(e) => setSkillSearch(e.target.value)}
          />
          {/* No `accept`: a skill is a folder, its files or a zip of it,
              assembled and reviewed in a modal. */}
          <CatalogHeaderImport
            label="Import skill"
            onClick={() => setSkillImportOpen(true)}
            title="Bring in a skill: its folder, its files or a zip of it"
          />
        </CatalogPageHeader>

        {skillBrowse.actionError ? (
          <div className={browseStyles.browseBanner} role="alert">
            <span>{skillBrowse.actionError}</span>
            <button
              type="button"
              className={browseStyles.browseBannerDismiss}
              aria-label="Dismiss"
              onClick={skillBrowse.dismissActionError}
            >
              ×
            </button>
          </div>
        ) : null}

        {skillBrowse.loading ? (
          <div className={browseStyles.empty}>Loading skills…</div>
        ) : skillBrowse.filtered.length === 0 ? (
          <div className={browseStyles.empty}>No skills match the current filters.</div>
        ) : (
          <section className={browseStyles.cardGrid}>
            {skillBrowse.filtered.map((skill) => (
              <SkillCatalogBrowseCard
                key={skill.name}
                skill={skill}
                // Follow what the drawer shows: on arrival it falls back to
                // the first row, which should read as selected.
                selected={skillBrowse.selectedSkill?.name === skill.name}
                onSelect={() => skillBrowse.setSelectedName(skill.name)}
                onViewDetails={() => setDetailSkillName(skill.name)}
                onContextMenu={(e) => {
                  e.preventDefault();
                  // Select first: the menu acts on this skill, so the drawer
                  // beside it should not still be describing another one.
                  skillBrowse.setSelectedName(skill.name);
                  setSkillMenu({ x: e.clientX, y: e.clientY, skill });
                }}
              />
            ))}
          </section>
        )}
      </main>

      <SkillCatalogBrowseDrawer
        skill={skillBrowse.selectedSkill}
        busyName={skillBrowse.busyName}
        catalogPublishAllowed={catalogPublishAllowed}
        onViewDetails={(skill) => setDetailSkillName(skill.name)}
        onPublish={(skill) => void skillBrowse.onPublish(skill)}
        onUnpublish={(skill) => void skillBrowse.onUnpublish(skill)}
        onRemove={(skill) => void skillBrowse.onRemove(skill)}
        onClose={() => skillBrowse.setSelectedName(null)}
        onLayoutChange={setDrawerSlotOpen}
      />

      {skillMenu ? (
        <CardContextMenu
          x={skillMenu.x}
          y={skillMenu.y}
          ariaLabel="Skill actions"
          items={skillCardActions()}
          onSelect={(id) => runSkillAction(id as CatalogCardActionId, skillMenu.skill)}
          onDismiss={() => setSkillMenu(null)}
        />
      ) : null}

      {detailSkill ? <SkillDetailModal skill={detailSkill} onClose={() => setDetailSkillName(null)} /> : null}

      {/* An imported skill joins the account's skills and the agents its
          review picked, so the skills, and who uses each, are read again.
          It is selected once they are: a selection the list does not hold
          yet falls back to the first row. */}
      {skillImportOpen ? (
        <SkillImportModal
          onClose={() => setSkillImportOpen(false)}
          onImported={(name) => {
            setSkillImportOpen(false);
            void skillBrowse.reload().then(() => skillBrowse.setSelectedName(name));
          }}
        />
      ) : null}
    </div>
  );
};

export default SkillCatalogBrowse;

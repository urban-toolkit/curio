/**
 * The account-scope Agent Catalog under /catalog/agents.
 *
 * The third peer of `/catalog/nodes` and `/catalog/data`: same three-column
 * grid from `CatalogBrowseLayout.module.css`, same rail (`CatalogRail`), same
 * header (`CatalogPageHeader`: kind icon + h1 + count, then search and import),
 * same card grid, same right-hand detail drawer.
 *
 * Scope is what separates this page from the in-canvas drawer. The drawer adds
 * an agent to ONE dataflow; this page adds it to the user's account, from
 * where it can be installed into any dataflow. The Node Catalog's page says
 * "Add to all projects" because installing there really does reach every
 * project - an agent import only makes the agent AVAILABLE to every project,
 * not present in any one of them. One vocabulary across the three catalogs was
 * judged worth more than that distinction, so the button borrows the label and
 * the intro carries the nuance ("makes it available to all your projects").
 *
 * The rail's Skills section lists the skills the agents read in the same
 * grid, with the same drawer and a details modal of their own. A skill is
 * added to an agent and removed from one in that agent's details. The
 * account's own skills come in through **Import skill**, as its agents come
 * in through **Import agent**, and the skill's drawer removes or publishes
 * one, as an agent's drawer does.
 */
import React, { useEffect, useState } from "react";

import type { AgentCard } from "../../services/agents";
import { agentCategoryKey } from "../../components/menus/nodes/agentsPalette/agentCategoryStyle";
import { packagesApi } from "../../services/packages";
import type { SortMode } from "../../services/packages";
import browseStyles from "../catalog/CatalogBrowseLayout.module.css";
import { AgentCatalogBrowseCard } from "./AgentCatalogBrowseCard";
import { AgentCatalogBrowseDrawer } from "./AgentCatalogBrowseDrawer";
import { useAgentCatalogBrowse } from "./useAgentCatalogBrowse";
import { CatalogHeaderImport } from "../catalog/CatalogHeaderImport";
import { CatalogPageHeader } from "../catalog/CatalogPageHeader";
import { CatalogRail } from "../catalog/CatalogRail";
import { AgentImportModal } from "../../components/agents/catalog/AgentImportModal";
import { AgentDetailModal } from "../../components/agents/catalog/AgentDetailModal";
import { AgentCatalogSettingsModal } from "../../components/agents/catalog/AgentCatalogSettingsModal";
import { SkillDetailModal } from "../../components/agents/catalog/SkillDetailModal";
import { SkillImportModal } from "../../components/agents/catalog/SkillImportModal";
import { CardContextMenu } from "../../components/catalog/CardContextMenu";
import {
  agentCardActions,
  skillCardActions,
  type CatalogCardActionId,
} from "../../components/catalog/catalogCardActions";
import type { SkillCard } from "../../services/agents";
import { SkillCatalogBrowseCard } from "./SkillCatalogBrowseCard";
import { SkillCatalogBrowseDrawer } from "./SkillCatalogBrowseDrawer";
import { useSkillCatalogBrowse, type SkillBrowseFilter } from "./useSkillCatalogBrowse";

/** What the grid lists: the agents, or, from the rail's Skills section, the
 *  skills they read. */
type BrowseView = "agents" | "skills";

export const AgentCatalogBrowse: React.FC = () => {
  const [drawerSlotOpen, setDrawerSlotOpen] = useState(false);
  const [view, setView] = useState<BrowseView>("agents");
  const [skillFilter, setSkillFilter] = useState<SkillBrowseFilter>("all");
  const [skillSearch, setSkillSearch] = useState("");
  const [detailSkillName, setDetailSkillName] = useState<string | null>(null);
  const [skillMenu, setSkillMenu] = useState<{ x: number; y: number; skill: SkillCard } | null>(null);
  const skillBrowse = useSkillCatalogBrowse(skillSearch, skillFilter);
  const showSkills = view === "skills";
  // Separate from `selectedCoord`, which drives the side drawer. Wiring both to
  // one setter is what made "View details" a no-op: on arrival the drawer is
  // already open on the first card, so the click had nothing left to change
  // (#189). The Data Catalog keeps the same two surfaces apart.
  const [detailCoord, setDetailCoord] = useState<string | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [skillImportOpen, setSkillImportOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  // Right-click. The card reports the event, the grid owns the menu - the same
  // division the projects page has used all along (#285).
  const [contextMenu, setContextMenu] = useState<{
    x: number;
    y: number;
    agent: AgentCard;
  } | null>(null);
  // The operator's publish switch, read as the Data Catalog page reads it.
  const [catalogPublishAllowed, setCatalogPublishAllowed] = useState(false);
  const {
    search,
    setSearch,
    sort,
    setSort,
    filter,
    setFilter,
    categoryFilter,
    setCategoryFilter,
    loading,
    busyCoord,
    actionError,
    dismissActionError,
    agents,
    filtered,
    categories,
    allCount,
    importedCount,
    setSelectedCoord,
    selectedAgent,
    onImport,
    onRemoveImport,
    onPublish,
    onUnpublish,
    reload,
  } = useAgentCatalogBrowse();

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

  const runAgentAction = (id: CatalogCardActionId, agent: AgentCard) => {
    switch (id) {
      case "add-to-all-projects":
        void onImport(agent);
        return;
      case "remove-from-all-projects":
        void onRemoveImport(agent);
        return;
      case "view-details":
        setDetailCoord(agent.dirName);
        return;
      // An agent is never offered the package catalog's update.
      case "update-all-projects":
        return;
    }
  };

  const runSkillAction = (id: CatalogCardActionId, skill: SkillCard) => {
    if (id === "view-details") setDetailSkillName(skill.name);
  };

  // From the unfiltered roster on purpose - the modal outlives a filter change.
  const detailAgent = detailCoord ? (agents.find((a) => a.dirName === detailCoord) ?? null) : null;
  const detailSkill = detailSkillName
    ? (skillBrowse.skills.find((s) => s.name === detailSkillName) ?? null)
    : null;
  // Switching to the agents, by any of their rows, leaves the skills.
  const showAgents = () => setView("agents");

  return (
    <div
      className={[browseStyles.page, drawerSlotOpen ? browseStyles.pageWithDrawer : ""]
        .filter(Boolean)
        .join(" ")}
    >
      <CatalogRail
        ariaLabel="Filter agents"
        all={{
          label: "All agents",
          count: allCount,
          active: !showSkills && filter === "all" && categoryFilter === "",
          onClick: () => {
            showAgents();
            setFilter("all");
            setCategoryFilter(() => "");
          },
        }}
        scope={{
          label: "In all projects",
          count: importedCount,
          active: !showSkills && filter === "imported",
          onClick: () => {
            showAgents();
            setFilter(!showSkills && filter === "imported" ? "all" : "imported");
          },
        }}
        sections={[
          {
            key: "category",
            label: "By category",
            entries: categories.map(([cat, count]) => ({
              value: cat,
              label: cat,
              count,
              active: !showSkills && categoryFilter === cat,
              onClick: () => {
                showAgents();
                setCategoryFilter((prev) => (!showSkills && prev === cat ? "" : cat));
              },
              // The card strips' palette key for this category.
              dotClassName: browseStyles[`agentDot_${agentCategoryKey(cat)}`] ?? "",
            })),
          },
          {
            // The skills the agents read. Either row lists them in the grid;
            // the agents' rows above go back to the agents.
            key: "skills",
            label: "Skills",
            entries: [
              {
                value: "all-skills",
                label: "All skills",
                count: skillBrowse.skills.length,
                active: showSkills && skillFilter === "all",
                onClick: () => {
                  if (showSkills && skillFilter === "all") {
                    showAgents();
                    return;
                  }
                  setView("skills");
                  setSkillFilter("all");
                },
              },
              {
                value: "core",
                label: "Core",
                count: skillBrowse.coreCount,
                active: showSkills && skillFilter === "core",
                onClick: () => {
                  setView("skills");
                  setSkillFilter(showSkills && skillFilter === "core" ? "all" : "core");
                },
              },
            ],
          },
        ]}
      />

      <main className={browseStyles.browseMain}>
        <CatalogPageHeader
          kind="agent"
          iconTitle="Agent catalog"
          title="Agent Catalog"
          count={showSkills ? skillBrowse.filtered.length : filtered.length}
          intro={
            showSkills ? (
              <>
                Skills the agents read: each tells an agent how to do one kind of task. Add one to an
                agent, or remove one, in that agent&apos;s details; the change reaches the agent in{" "}
                <strong>all your projects</strong>.
              </>
            ) : (
              <>
                Agents in the shared catalog. Adding one here makes it available to{" "}
                <strong>all your projects</strong>, present and future; add it to a single project from
                that project&apos;s Agent Catalog.
              </>
            )
          }
          viewTools={
            showSkills ? null : (
              <select
                className={browseStyles.sortSelect}
                aria-label="Sort agents"
                value={sort}
                onChange={(e) => setSort(e.target.value as SortMode)}
              >
                <option value="new">Sort: Newest</option>
                <option value="name">Sort: Name</option>
              </select>
            )
          }
        >
          {showSkills ? (
            <input
              className={browseStyles.hubSearch}
              type="search"
              placeholder="Search skills…"
              value={skillSearch}
              onChange={(e) => setSkillSearch(e.target.value)}
            />
          ) : (
            <input
              className={browseStyles.hubSearch}
              type="search"
              placeholder="Search agents…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          )}
          {/* No `accept`: an agent package is a manifest plus its prompt
              files, and a skill a folder, its files or a zip, each assembled
              and reviewed in a modal. */}
          {showSkills ? (
            <CatalogHeaderImport
              label="Import skill"
              onClick={() => setSkillImportOpen(true)}
              title="Bring in a skill: its folder, its files or a zip of it"
            />
          ) : (
            <CatalogHeaderImport
              label="Import agent"
              onClick={() => setImportOpen(true)}
              title="Upload your own agent definition"
            />
          )}
          <button
            type="button"
            className={browseStyles.publishButton}
            data-tooltip="Values your agents read when they run"
            onClick={() => setSettingsOpen(true)}
          >
            Settings
          </button>
        </CatalogPageHeader>

        {(showSkills ? skillBrowse.actionError : actionError) ? (
          <div className={browseStyles.browseBanner} role="alert">
            <span>{showSkills ? skillBrowse.actionError : actionError}</span>
            <button
              type="button"
              className={browseStyles.browseBannerDismiss}
              aria-label="Dismiss"
              onClick={showSkills ? skillBrowse.dismissActionError : dismissActionError}
            >
              ×
            </button>
          </div>
        ) : null}

        {showSkills ? (
          skillBrowse.loading ? (
            <div className={browseStyles.empty}>Loading skills…</div>
          ) : skillBrowse.filtered.length === 0 ? (
            <div className={browseStyles.empty}>No skills match the current filters.</div>
          ) : (
            <section className={browseStyles.cardGrid}>
              {skillBrowse.filtered.map((skill) => (
                <SkillCatalogBrowseCard
                  key={skill.name}
                  skill={skill}
                  selected={skillBrowse.selectedSkill?.name === skill.name}
                  onSelect={() => skillBrowse.setSelectedName(skill.name)}
                  onViewDetails={() => setDetailSkillName(skill.name)}
                  onContextMenu={(e) => {
                    e.preventDefault();
                    skillBrowse.setSelectedName(skill.name);
                    setSkillMenu({ x: e.clientX, y: e.clientY, skill });
                  }}
                />
              ))}
            </section>
          )
        ) : loading ? (
          <div className={browseStyles.empty}>Loading agents…</div>
        ) : filtered.length === 0 ? (
          <div className={browseStyles.empty}>No agents match the current filters.</div>
        ) : (
          <section className={browseStyles.cardGrid}>
            {filtered.map((agent) => (
              <AgentCatalogBrowseCard
                key={agent.dirName}
                agent={agent}
                // Follow what the drawer actually shows, not the raw state:
                // on arrival the selection is `undefined` and the drawer falls
                // back to the first row, which should read as selected.
                selected={selectedAgent?.dirName === agent.dirName}
                onSelect={() => setSelectedCoord(agent.dirName)}
                onViewDetails={() => setDetailCoord(agent.dirName)}
                onContextMenu={(e) => {
                  e.preventDefault();
                  // Select first: the menu acts on this agent, so the drawer
                  // beside it should not still be describing another one.
                  setSelectedCoord(agent.dirName);
                  setContextMenu({ x: e.clientX, y: e.clientY, agent });
                }}
              />
            ))}
          </section>
        )}
      </main>

      {showSkills ? (
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
      ) : (
        <AgentCatalogBrowseDrawer
          agent={selectedAgent}
          busyCoord={busyCoord}
          catalogPublishAllowed={catalogPublishAllowed}
          onImport={(a) => void onImport(a)}
          onRemoveImport={(a) => void onRemoveImport(a)}
          onPublish={(a) => void onPublish(a)}
          onUnpublish={(a) => void onUnpublish(a)}
          onViewDetails={(a) => setDetailCoord(a.dirName)}
          onClose={() => setSelectedCoord(null)}
          onLayoutChange={setDrawerSlotOpen}
        />
      )}

      {contextMenu ? (
        <CardContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          ariaLabel="Agent actions"
          items={agentCardActions({ imported: contextMenu.agent.imported })}
          onSelect={(id) => runAgentAction(id as CatalogCardActionId, contextMenu.agent)}
          onDismiss={() => setContextMenu(null)}
        />
      ) : null}

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

      {detailAgent ? (
        <AgentDetailModal
          agent={detailAgent}
          onClose={() => {
            setDetailCoord(null);
            // A skill added or removed there changes who uses it.
            void skillBrowse.reload();
          }}
        />
      ) : null}

      {detailSkill ? <SkillDetailModal skill={detailSkill} onClose={() => setDetailSkillName(null)} /> : null}

      {settingsOpen ? <AgentCatalogSettingsModal onClose={() => setSettingsOpen(false)} /> : null}

      {/* An imported skill joins the account's skills and the agents its
          review picked, so the skills, and who uses each, are read again. */}
      {skillImportOpen ? (
        <SkillImportModal
          onClose={() => setSkillImportOpen(false)}
          onImported={(name) => {
            setSkillImportOpen(false);
            skillBrowse.setSelectedName(name);
            void skillBrowse.reload();
          }}
        />
      ) : null}

      {/* The same modal the drawer's footer opens. Uploading writes a new
          definition into the account, so the roster has to be re-read. */}
      {importOpen ? (
        <AgentImportModal
          onClose={() => setImportOpen(false)}
          onImported={(dirName) => {
            setImportOpen(false);
            setSelectedCoord(dirName);
            void reload();
          }}
        />
      ) : null}
    </div>
  );
};

export default AgentCatalogBrowse;

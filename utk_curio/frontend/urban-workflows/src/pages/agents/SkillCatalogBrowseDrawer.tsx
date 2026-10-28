import React from "react";

import { CatalogBrowseDrawerShell } from "../catalog/CatalogBrowseDrawerShell";
import {
  CatalogBrowseDrawerBody,
  CatalogDrawerList,
  CatalogDrawerSection,
} from "../catalog/CatalogBrowseDrawerBody";
import { CatalogKindIcon } from "../../components/catalog/CatalogKindVisuals";
import {
  CatalogPublishPill,
  shouldShowPublishPill,
} from "../../components/packages/CatalogPublishPill";
import { SKILL_SOURCE_WORDS, skillByline, skillServes, type SkillCard } from "../../services/agents";
import styles from "../catalog/CatalogBrowseLayout.module.css";

export interface SkillCatalogBrowseDrawerProps {
  skill: SkillCard | null;
  busyName?: string | null;
  catalogPublishAllowed?: boolean;
  onViewDetails: (skill: SkillCard) => void;
  onPublish?: (skill: SkillCard) => void;
  onUnpublish?: (skill: SkillCard) => void;
  onRemove?: (skill: SkillCard) => void;
  onClose: () => void;
  onLayoutChange?: (slotOpen: boolean) => void;
}

/**
 * The right-hand drawer on `/catalog/agents` when the rail shows skills.
 *
 * Composed from `CatalogBrowseDrawerBody`, as every browse drawer is
 * (`catalogDrawerParity.test.ts`). It names the agents that use the skill and
 * offers its full details; a skill is added to an agent, and removed from
 * one, in that agent's details. A skill the account holds, one it imported or
 * its copy of one from the shared catalog, has **Remove from your skills**,
 * as an agent the account added has **Remove from all projects**; one it
 * imported has the shared publish pill, as an agent it imported does.
 */
export function SkillCatalogBrowseDrawer({
  skill,
  busyName = null,
  catalogPublishAllowed = false,
  onViewDetails,
  onPublish,
  onUnpublish,
  onRemove,
  onClose,
  onLayoutChange,
}: SkillCatalogBrowseDrawerProps) {
  return (
    <CatalogBrowseDrawerShell presented={skill != null} onLayoutChange={onLayoutChange}>
      {skill ? (
        <SkillDrawerContent
          skill={skill}
          busy={busyName === skill.name}
          catalogPublishAllowed={catalogPublishAllowed}
          onViewDetails={onViewDetails}
          onPublish={onPublish}
          onUnpublish={onUnpublish}
          onRemove={onRemove}
          onClose={onClose}
        />
      ) : null}
    </CatalogBrowseDrawerShell>
  );
}

function SkillDrawerContent({
  skill,
  busy,
  catalogPublishAllowed,
  onViewDetails,
  onPublish,
  onUnpublish,
  onRemove,
  onClose,
}: {
  skill: SkillCard;
  busy: boolean;
  catalogPublishAllowed: boolean;
  onViewDetails: (skill: SkillCard) => void;
  onPublish?: (skill: SkillCard) => void;
  onUnpublish?: (skill: SkillCard) => void;
  onRemove?: (skill: SkillCard) => void;
  onClose: () => void;
}) {
  const serves = skillServes(skill);
  const source = skill.source ?? "curio";
  const showPublishPill = shouldShowPublishPill({
    isPublished: Boolean(skill.published),
    allowPublish: catalogPublishAllowed,
    canPublish: Boolean(skill.publishable || skill.publishedByYou),
  });
  return (
    <CatalogBrowseDrawerBody
      kind="skill"
      headerTitle="Skill details"
      onClose={onClose}
      hero={
        <div className={styles.drawerKindHero}>
          <CatalogKindIcon kind="skill" size="lg" title="Skill" />
        </div>
      }
      title={skill.name}
      badges={
        <>
          {skill.core ? <span className={styles.drawerCategoryBadge}>core</span> : null}
          {skill.removable ? <span className={styles.drawerInstalledBadge}>✓ In your skills</span> : null}
        </>
      }
      subtitle={`${skillByline(skill)}${skill.version ? ` · v${skill.version}` : ""}`}
      metaLeft={skill.name}
      metaRight={skill.license ?? ""}
      // A skill carries no timestamp, so there is nothing to call fresh.
      fresh={false}
      description={skill.description}
      infoLabel="Skill info"
      infoRows={[
        { label: "Serves", value: skill.core ? "Every call" : serves.length ? serves.join(", ") : "A chat that needs it" },
        { label: "From", value: SKILL_SOURCE_WORDS[source] },
        skill.published ? { label: "Shared catalog", value: skill.publishedByYou ? "Published by you" : "Published" } : null,
        skill.license ? { label: "License", value: skill.license } : null,
        skill.compatibility ? { label: "Compatibility", value: skill.compatibility } : null,
        { label: "Files", value: skill.files.length ? skill.files.join(", ") : "None besides SKILL.md" },
      ]}
      sections={
        <CatalogDrawerSection label="Used by">
          <CatalogDrawerList
            items={
              skill.agents.length > 0
                ? skill.agents.map((agent) => (
                    <li key={agent.coord}>
                      {agent.name}
                      {agent.added ? " (added by you)" : ""}
                    </li>
                  ))
                : [<li key="none">No agent</li>]
            }
          />
        </CatalogDrawerSection>
      }
      primaryAction={
        skill.removable && onRemove ? (
          <button className={styles.destructiveBtn} type="button" disabled={busy} onClick={() => onRemove(skill)}>
            {busy ? "Removing…" : "Remove from your skills"}
          </button>
        ) : undefined
      }
      secondaryAction={
        <button className={styles.drawerLinkButton} type="button" onClick={() => onViewDetails(skill)}>
          View details
        </button>
      }
      publishPill={
        showPublishPill && onPublish ? (
          <CatalogPublishPill
            variant="drawer"
            dirName={skill.name}
            published={Boolean(skill.published)}
            allowPublish={catalogPublishAllowed}
            busy={busy}
            onPublish={() => onPublish(skill)}
            onUnpublish={skill.publishedByYou && onUnpublish ? () => onUnpublish(skill) : undefined}
            publishActionTitle="Publish this skill into the shared catalog, for every account on this Curio"
            unpublishActionTitle={`Remove ${skill.name} from the shared catalog`}
            itemLabel={skill.name}
            catalogLabel="the shared catalog"
          />
        ) : null
      }
    />
  );
}

export default SkillCatalogBrowseDrawer;

import React from "react";

import { CatalogBrowseDrawerShell } from "../catalog/CatalogBrowseDrawerShell";
import {
  CatalogBrowseDrawerBody,
  CatalogDrawerList,
  CatalogDrawerSection,
} from "../catalog/CatalogBrowseDrawerBody";
import { CatalogKindIcon } from "../../components/catalog/CatalogKindVisuals";
import { skillServes, type SkillCard } from "../../services/agents";
import styles from "../catalog/CatalogBrowseLayout.module.css";

export interface SkillCatalogBrowseDrawerProps {
  skill: SkillCard | null;
  onViewDetails: (skill: SkillCard) => void;
  onClose: () => void;
  onLayoutChange?: (slotOpen: boolean) => void;
}

/**
 * The right-hand drawer on `/catalog/agents` when the rail shows skills.
 *
 * Composed from `CatalogBrowseDrawerBody`, as every browse drawer is
 * (`catalogDrawerParity.test.ts`). A skill has no primary action here: it is
 * added to an agent, and removed from one, in that agent's details, so the
 * drawer names the agents that use it and offers its full details.
 */
export function SkillCatalogBrowseDrawer({
  skill,
  onViewDetails,
  onClose,
  onLayoutChange,
}: SkillCatalogBrowseDrawerProps) {
  return (
    <CatalogBrowseDrawerShell presented={skill != null} onLayoutChange={onLayoutChange}>
      {skill ? <SkillDrawerContent skill={skill} onViewDetails={onViewDetails} onClose={onClose} /> : null}
    </CatalogBrowseDrawerShell>
  );
}

function SkillDrawerContent({
  skill,
  onViewDetails,
  onClose,
}: {
  skill: SkillCard;
  onViewDetails: (skill: SkillCard) => void;
  onClose: () => void;
}) {
  const serves = skillServes(skill);
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
      badges={skill.core ? <span className={styles.drawerCategoryBadge}>core</span> : null}
      subtitle={`${skill.author ?? "curio"}${skill.version ? ` · v${skill.version}` : ""}`}
      metaLeft={skill.name}
      metaRight={skill.license ?? ""}
      // A skill carries no timestamp, so there is nothing to call fresh.
      fresh={false}
      description={skill.description}
      infoLabel="Skill info"
      infoRows={[
        { label: "Serves", value: skill.core ? "Every call" : serves.length ? serves.join(", ") : "A chat that needs it" },
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
      secondaryAction={
        <button className={styles.drawerLinkButton} type="button" onClick={() => onViewDetails(skill)}>
          View details
        </button>
      }
    />
  );
}

export default SkillCatalogBrowseDrawer;

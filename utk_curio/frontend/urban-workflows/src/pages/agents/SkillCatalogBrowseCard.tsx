import React from "react";

import { CatalogItemStripHeader } from "../../components/catalog/CatalogKindVisuals";
import { skillServes, type SkillCard } from "../../services/agents";
import styles from "../catalog/CatalogBrowseLayout.module.css";
import cardStyles from "./SkillCatalogBrowseCard.module.css";

export interface SkillCatalogBrowseCardProps {
  skill: SkillCard;
  selected: boolean;
  onSelect: () => void;
  onViewDetails: () => void;
  /** Right-click. The grid owns the menu, so the card only reports it. */
  onContextMenu?: (e: React.MouseEvent) => void;
}

/**
 * One skill in the Agent Catalog's grid, when the rail's Skills section is
 * chosen.
 *
 * The agent card's structure, painted from the same stylesheet: strip header,
 * body (name, author and version, description, what it serves), meta row
 * (how many agents use it), actions. `data-skill-name` names it for tests, as
 * `data-agent-coord` names an agent's card.
 */
export function SkillCatalogBrowseCard({
  skill,
  selected,
  onSelect,
  onViewDetails,
  onContextMenu,
}: SkillCatalogBrowseCardProps) {
  const tags = (skill.core ? ["every call"] : skillServes(skill)).slice(0, 3);
  const users = skill.agents.length;

  return (
    <article
      className={[
        styles.card,
        selected ? styles.cardActive : "",
        // Both, as the agent card applies both: the coloured border is the
        // compound `.cardActive.card_skill` in THIS module.
        selected ? cardStyles.cardActive : "",
        cardStyles.card_skill,
      ]
        .filter(Boolean)
        .join(" ")}
      data-skill-name={skill.name}
      role="button"
      tabIndex={0}
      onContextMenu={onContextMenu}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") onSelect();
      }}
    >
      <div className={`${styles.cardStrip} ${cardStyles.strip_skill}`}>
        <CatalogItemStripHeader
          kind="skill"
          badge={skill.core ? <span className={styles.cardFormatBadge}>core</span> : undefined}
        />
      </div>

      <div className={styles.cardBody}>
        <h2 className={styles.cardTitle}>{skill.name}</h2>
        <p className={styles.publisher}>
          {skill.author ?? "curio"}
          {skill.version ? ` · v${skill.version}` : null}
        </p>
        <p className={styles.cardDescription}>{skill.description}</p>
        <div className={styles.tagRow} data-curio-tag-row="true">
          {tags.map((tag) => (
            <span key={tag} className={styles.tag} data-curio-tag-chip="true">
              {tag}
            </span>
          ))}
        </div>
      </div>

      <div className={styles.cardMeta}>
        <span className={styles.metaLeft}>
          {users} agent{users === 1 ? "" : "s"}
        </span>
        <span className={styles.metaRight}>{skill.license ?? ""}</span>
      </div>

      <div className={styles.cardActions}>
        <div className={styles.cardActionsLeft}>
          {skill.agents.some((agent) => agent.added) ? (
            <span className={styles.cardStatus}>✓ Added by you</span>
          ) : null}
        </div>
        <div className={styles.cardActionsRight}>
          <button
            className={styles.linkButton}
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onViewDetails();
            }}
          >
            View details
          </button>
        </div>
      </div>
    </article>
  );
}

export default SkillCatalogBrowseCard;

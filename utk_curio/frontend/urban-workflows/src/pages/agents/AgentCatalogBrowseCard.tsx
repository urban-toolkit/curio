import React from "react";

import { CatalogItemStripHeader } from "../../components/catalog/CatalogKindVisuals";
import {
  CatalogPublishPill,
  shouldShowPublishPill,
} from "../../components/packages/CatalogPublishPill";
import type { AgentCard } from "../../api/agentsApi";
import { agentCategoryKey } from "../../components/menus/nodes/agentsPalette/agentCategoryStyle";
import styles from "../catalog/CatalogBrowseLayout.module.css";
import cardStyles from "./AgentCatalogBrowseCard.module.css";

export interface AgentCatalogBrowseCardProps {
  agent: AgentCard;
  selected: boolean;
  busy: boolean;
  onSelect: () => void;
  onViewDetails: () => void;
  onPublish: (agent: AgentCard) => void;
  catalogPublishAllowed: boolean;
}

/**
 * One agent in the `/catalog/agents` grid.
 *
 * Structurally identical to `DataCatalogBrowseCard` and `PackageBrowseCard`,
 * and painted from the same stylesheet: strip header, body (title, publisher,
 * description, tags), meta row, actions. The description carries a non-breaking
 * space when empty - the peers do the same - so a card with no description
 * keeps the grid's rows the same height instead of riding up.
 *
 * No accent stripe: it was dropped from every catalog card because the strip
 * and the kind icon already carry the category.
 */
export function AgentCatalogBrowseCard({
  agent,
  selected,
  busy,
  onSelect,
  onViewDetails,
  onPublish,
  catalogPublishAllowed,
}: AgentCatalogBrowseCardProps) {
  const categoryKey = agentCategoryKey(agent.category);
  // Tags read as the agent's shape: what it does, then what it attaches to.
  const tags = [agent.category, ...agent.hooks.map((h) => `hook: ${h}`)]
    .filter(Boolean)
    .slice(0, 3) as string[];
  const showPublishPill = shouldShowPublishPill({
    isPublished: agent.published,
    allowPublish: catalogPublishAllowed,
    canPublish: agent.publishable,
  });

  return (
    <article
      className={[
        styles.card,
        selected ? styles.cardActive : "",
        // Both, deliberately. The coloured border comes from the compound
        // `.cardActive.card_<key>` in THIS module, and CSS modules hash each
        // class per file - so the shared `cardActive` above cannot satisfy it.
        // Without the local one the compound never matched and a selected agent
        // card kept `border: 1.5px solid transparent` (#188). PackageBrowseCard
        // applies both for the same reason.
        selected ? cardStyles.cardActive : "",
        cardStyles[`card_${categoryKey}`] ?? "",
      ]
        .filter(Boolean)
        .join(" ")}
      data-agent-coord={agent.dirName}
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") onSelect();
      }}
    >
      <div className={`${styles.cardStrip} ${cardStyles[`strip_${categoryKey}`] ?? ""}`}>
        <CatalogItemStripHeader
          kind="agent"
          badge={<span className={styles.cardFormatBadge}>{agent.category}</span>}
          trailing={
            agent.imported ? <span className={styles.stripBadgePopular}>✓ In your account</span> : null
          }
        />
      </div>

      <div className={styles.cardBody}>
        <h2 className={styles.cardTitle}>{agent.name}</h2>
        <p className={styles.publisher}>
          {agent.provenance?.publisher ?? "curio"} · v{agent.version}
        </p>
        <p className={styles.cardDescription} {...(!agent.purpose ? { "aria-hidden": true } : {})}>
          {agent.purpose || " "}
        </p>
        <div className={styles.tagRow}>
          {tags.map((tag) => (
            <span key={tag} className={styles.tag} data-curio-tag-chip="true">
              {tag}
            </span>
          ))}
        </div>
      </div>

      <div className={styles.cardMeta}>
        <span className={styles.metaLeft}>
          {agent.capabilities.length} capabilit{agent.capabilities.length === 1 ? "y" : "ies"}
        </span>
        <span className={styles.metaRight}>{agent.id}</span>
      </div>

      <div className={styles.cardActions}>
        <div className={styles.cardActionsLeft}>
          {showPublishPill ? (
            <CatalogPublishPill
              variant="hub"
              dirName={agent.dirName}
              published={agent.published}
              allowPublish={catalogPublishAllowed}
              busy={busy}
              onPublish={() => onPublish(agent)}
              publishedTitle="Listed in the Agent Catalog"
              publishActionTitle="Publish this agent into the shared catalog"
            />
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

export default AgentCatalogBrowseCard;

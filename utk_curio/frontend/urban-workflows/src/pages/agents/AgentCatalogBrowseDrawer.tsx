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
import type { AgentCard } from "../../api/agentsApi";
import styles from "../catalog/CatalogBrowseLayout.module.css";

export interface AgentCatalogBrowseDrawerProps {
  agent: AgentCard | null;
  busyCoord: string | null;
  catalogPublishAllowed: boolean;
  onImport: (agent: AgentCard) => void;
  onRemoveImport: (agent: AgentCard) => void;
  onPublish: (agent: AgentCard) => void;
  onViewDetails?: (agent: AgentCard) => void;
  onUnpublish: (agent: AgentCard) => void;
  onClose: () => void;
  onLayoutChange?: (slotOpen: boolean) => void;
}

/**
 * The right-hand detail drawer on `/catalog/agents`.
 *
 * Composed from `CatalogBrowseDrawerBody`, which is the point: the Node and
 * Data drawers used to hand-assemble the same screen and drifted - four
 * renderings of the word "Published", different badge semantics, inline styles
 * on one side. Feeding the shared body means a change to the layout lands on
 * all three catalogs at once. `catalogDrawerParity.test.ts` holds this.
 */
export function AgentCatalogBrowseDrawer({
  agent,
  busyCoord,
  catalogPublishAllowed,
  onImport,
  onRemoveImport,
  onPublish,
  onUnpublish,
  onViewDetails,
  onClose,
  onLayoutChange,
}: AgentCatalogBrowseDrawerProps) {
  return (
    <CatalogBrowseDrawerShell presented={agent != null} onLayoutChange={onLayoutChange}>
      {agent ? (
        <AgentCatalogBrowseDrawerContent
          agent={agent}
          busyCoord={busyCoord}
          catalogPublishAllowed={catalogPublishAllowed}
          onImport={onImport}
          onRemoveImport={onRemoveImport}
          onPublish={onPublish}
          onUnpublish={onUnpublish}
          onViewDetails={onViewDetails}
          onClose={onClose}
        />
      ) : null}
    </CatalogBrowseDrawerShell>
  );
}

type ContentProps = Omit<AgentCatalogBrowseDrawerProps, "agent" | "onLayoutChange"> & {
  agent: AgentCard;
};

function AgentCatalogBrowseDrawerContent({
  agent,
  busyCoord,
  catalogPublishAllowed,
  onImport,
  onRemoveImport,
  onPublish,
  onUnpublish,
  onViewDetails,
  onClose,
}: ContentProps) {
  const busy = busyCoord === agent.dirName;
  const showPublishPill = shouldShowPublishPill({
    isPublished: agent.published,
    allowPublish: catalogPublishAllowed,
    canPublish: agent.publishable,
  });

  return (
    <CatalogBrowseDrawerBody
      kind="agent"
      headerTitle="Agent details"
      onClose={onClose}
      hero={
        <div className={styles.drawerKindHero}>
          <CatalogKindIcon kind="agent" size="lg" title="Agent" />
        </div>
      }
      title={agent.name}
      badges={
        <>
          <span className={styles.drawerCategoryBadge}>{agent.category}</span>
          {agent.imported ? (
            <span className={styles.drawerInstalledBadge}>✓ In all projects</span>
          ) : null}
        </>
      }
      subtitle={`${agent.provenance?.publisher ?? "curio"} · v${agent.version}`}
      metaLeft={agent.id}
      metaRight={agent.provenance?.trust ?? "built-in"}
      // Agent cards carry no timestamp, so there is nothing to call fresh.
      // Reporting false leaves the meta dot grey rather than inventing recency.
      fresh={false}
      description={agent.purpose}
      infoLabel="Agent info"
      infoRows={[
        { label: "Category", value: agent.category },
        { label: "Version", value: agent.version },
        { label: "Publisher", value: agent.provenance?.publisher ?? "curio" },
        { label: "Trust", value: agent.provenance?.trust ?? "built-in" },
        agent.hooks.length > 0 ? { label: "Attaches to", value: agent.hooks.join(", ") } : null,
      ]}
      tags={agent.capabilities}
      sections={
        agent.requiresAgents.length > 0 ? (
          <CatalogDrawerSection label="Requires">
            {/* Disclosed BEFORE the click, so adding an agent never silently
                pulls in others. The drawer next door does the same on its Add
                button's label. Only resolvability is shown, not
                `installedInProject`: this page has no project, and reporting a
                per-project state here would be reporting whichever dataflow
                happened to be open last. */}
            <CatalogDrawerList
              items={agent.requiresAgents.map((req) => (
                <li key={req.id}>
                  {req.name}
                  {req.visible ? "" : " (unavailable)"}
                </li>
              ))}
            />
          </CatalogDrawerSection>
        ) : null
      }
      primaryAction={
        agent.imported ? (
          <button
            className={styles.destructiveBtn}
            type="button"
            disabled={busy}
            onClick={() => onRemoveImport(agent)}
          >
            {busy ? "Removing…" : "Remove from all projects"}
          </button>
        ) : (
          <button
            className={styles.addToPaletteBtn}
            type="button"
            disabled={busy}
            onClick={() => onImport(agent)}
          >
            {busy ? "Adding…" : "Add to all projects"}
          </button>
        )
      }
      secondaryAction={
        /* See the Node drawer: one shape for all three right bars. */
        <button
          className={styles.drawerLinkButton}
          type="button"
          onClick={() => onViewDetails?.(agent)}
        >
          View details
        </button>
      }
      publishPill={
        showPublishPill ? (
          <CatalogPublishPill
            /* See the Data drawer: same slot, same full-width 42px box as the
               primary action directly above it. */
            variant="drawer"
            dirName={agent.dirName}
            published={agent.published}
            allowPublish={catalogPublishAllowed}
            busy={busy}
            onPublish={() => onPublish(agent)}
            onUnpublish={() => onUnpublish(agent)}
            publishActionTitle="Publish this agent into the shared catalog"
            unpublishActionTitle={`Remove ${agent.name} from the Agent Catalog`}
            itemLabel={agent.name}
            catalogLabel="the Agent Catalog"
          />
        ) : null
      }
    />
  );
}

export default AgentCatalogBrowseDrawer;

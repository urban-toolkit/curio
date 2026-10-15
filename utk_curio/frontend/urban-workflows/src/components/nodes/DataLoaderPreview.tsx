import React from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import type { IconDefinition } from "@fortawesome/fontawesome-svg-core";
import { faCircleCheck, faCircleMinus, faCircleXmark, faSpinner } from "@fortawesome/free-solid-svg-icons";
import { dataTypeVisual, SOURCE_KIND_VISUALS } from "../../constants/dataTypeVisuals";
import {
  shortenPath,
  type LoaderProfile,
  type LoaderSource,
} from "../../services/datasetCatalog/loaderProfile";
import { DataLoaderGlyph, dataTypeStyle } from "./DataLoaderGlyph";
import styles from "./DataLoader.module.css";

/** The line under the type: what the node reads, in words a user knows. */
export function loaderTitle(source: LoaderSource | undefined): string {
  if (!source) return "Custom loader";
  switch (source.kind) {
    case "catalog":
      return source.title || source.address;
    case "disk": {
      if (!source.address) return "File (path built in code)";
      const parts = source.address.split(/[\\/]/);
      return parts[parts.length - 1] || source.address;
    }
    case "api":
      return source.address || "API (address built in code)";
    case "inline":
      return "Defined in code";
    default:
      return "Custom loader";
  }
}

/** One sentence for a screen reader: "Loads GeoJSON from the Data Catalog: Chicago community areas". */
export function loaderAccessibleName(profile: LoaderProfile, detecting = false): string {
  const source = profile.sources[0];
  const type = detecting ? "data (detecting its type)" : profile.dataType === "unknown" ? "data" : dataTypeVisual(profile.dataType).label;
  const from = source ? SOURCE_KIND_VISUALS[source.kind].label : "custom code";
  const where = source && source.kind !== "inline" && source.kind !== "unknown" ? `: ${loaderTitle(source)}` : "";
  const fromText = source?.kind === "catalog" ? "the Data Catalog" : source?.kind === "inline" ? "data defined in its code" : from.toLowerCase();
  return `Loads ${type} from ${fromText}${where}`;
}

function SourceLine({
  source,
  more,
  onOpenDataset,
}: {
  source: LoaderSource;
  more: number;
  onOpenDataset?: (datasetId: string) => void;
}) {
  const visual = SOURCE_KIND_VISUALS[source.kind];
  const shown = source.kind === "disk" ? shortenPath(source.address) : source.address;
  return (
    <span className={styles.source}>
      <LineIcon icon={visual.glyph} />
      <span className={styles.sourceKind}>{visual.label}</span>
      {shown ? (
        <>
          <span aria-hidden="true">·</span>
          {source.kind === "catalog" && source.datasetId && onOpenDataset ? (
            <button
              type="button"
              className={`${styles.addressLink} nodrag`}
              title={`Open ${source.address} in the Data Catalog`}
              onClick={(event) => {
                event.stopPropagation();
                onOpenDataset(source.datasetId!);
              }}
            >
              {shown}
            </button>
          ) : (
            <span className={styles.address} title={source.address}>
              {shown}
            </span>
          )}
        </>
      ) : null}
      {more > 0 ? <span className={styles.more}>+{more}</span> : null}
    </span>
  );
}

/** A line's glyph, in the slot both lines share; none leaves the slot empty. */
function LineIcon({ icon, className }: { icon?: IconDefinition; className?: string }) {
  return (
    <span className={styles.lineIcon} aria-hidden="true">
      {icon ? <FontAwesomeIcon icon={icon} className={className} /> : null}
    </span>
  );
}

function StatusLine({
  outputCode,
  profile,
  detecting,
}: {
  outputCode?: string;
  profile: LoaderProfile;
  detecting: boolean;
}) {
  if (outputCode === "exec") {
    return (
      <span className={styles.status}>
        <LineIcon icon={faSpinner} className={styles.spin} />
        <span>Running…</span>
      </span>
    );
  }
  if (outputCode === "success") {
    return (
      <span className={styles.status}>
        <LineIcon icon={faCircleCheck} className={styles.ok} />
        <span>Loaded</span>
      </span>
    );
  }
  if (outputCode === "error") {
    return (
      <span className={styles.status}>
        <LineIcon icon={faCircleXmark} className={styles.failed} />
        <span>The last run failed; the reason is below the node</span>
      </span>
    );
  }
  if (detecting) {
    return (
      <span className={styles.status}>
        <LineIcon />
        <span>Checking the returned data once</span>
      </span>
    );
  }
  return (
    <span className={styles.status}>
      {/* Not run: a circle with a dash, in off-black. Never the play glyph,
          which is the header's Play button and must stay the only one. */}
      <LineIcon icon={faCircleMinus} className={styles.notRun} />
      <span>{profile.dataType === "unknown" ? "Run to see the type" : "Not run yet"}</span>
    </span>
  );
}

/**
 * A loader's preview: its data type on the typed database, what it reads, and
 * where from. Replaces the editor's pane while the node is in preview; the
 * editor stays mounted underneath, so its cursor and undo history survive.
 */
export function DataLoaderPreview({
  profile,
  detecting = false,
  outputCode,
  onOpenDataset,
  pendingProposal = false,
  onShowCode,
}: {
  profile: LoaderProfile;
  detecting?: boolean;
  outputCode?: string;
  onOpenDataset?: (datasetId: string) => void;
  /** A collaborator's code change waits for review: say so, with a way to it. */
  pendingProposal?: boolean;
  onShowCode?: () => void;
}) {
  const primary = profile.sources[0];
  const visual = dataTypeVisual(profile.dataType);
  const typeLabel = detecting ? "Detecting type…" : visual.label;
  return (
    <div
      className={styles.preview}
      style={dataTypeStyle(profile.dataType)}
      role="group"
      aria-label={loaderAccessibleName(profile, detecting)}
      data-testid="data-loader-preview"
      data-data-type={profile.dataType}
      data-source-kind={primary?.kind ?? "unknown"}
    >
      <div className={styles.identity}>
        <DataLoaderGlyph dataType={profile.dataType} detecting={detecting} />
        <div className={styles.meta}>
          <span className={styles.typeLabel}>
            {typeLabel}
            {profile.extraTypes > 0 && !detecting ? (
              <span className={styles.extraTypes}>+{profile.extraTypes}</span>
            ) : null}
          </span>
          <span className={styles.title} title={loaderTitle(primary)}>
            {loaderTitle(primary)}
          </span>
        </div>
      </div>
      <div className={styles.separator} />
      <div className={styles.facts}>
        {primary ? (
          <SourceLine source={primary} more={profile.sources.length - 1} onOpenDataset={onOpenDataset} />
        ) : null}
        {pendingProposal ? (
          <span className={styles.status}>
            <LineIcon />
            <span>A code change is waiting for review.</span>
            {onShowCode ? (
              <button type="button" className={`${styles.inlineButton} nodrag`} onClick={onShowCode}>
                Show code
              </button>
            ) : null}
          </span>
        ) : (
          <StatusLine outputCode={outputCode} profile={profile} detecting={detecting} />
        )}
      </div>
    </div>
  );
}

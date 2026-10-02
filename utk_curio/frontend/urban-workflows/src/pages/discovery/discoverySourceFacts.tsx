import React from "react";

import { requestSourceKey } from "../../components/connectionKeys/connectionKeysRequest";
import browseStyles from "../catalog/CatalogBrowseLayout.module.css";
import { DISCOVERY_PROVIDER_LABEL, type DiscoverySourceRow } from "../../services/discoveryCatalog";

/**
 * What the Discovery Catalog says about one source, for its drawer and its
 * details modal alike.
 *
 * Both render these rows, so the two views cannot disagree about a portal the
 * way the three catalogs' hand-assembled drawers once disagreed about
 * "Published". Each view lays them out in its own container.
 */

export interface DiscoverySourceFact {
  label: string;
  value: React.ReactNode;
}

function bytesLabel(bytes: number): string {
  const mb = bytes / (1024 * 1024);
  return mb >= 1 ? `${Math.round(mb)} MB` : `${Math.round(bytes / 1024)} KB`;
}

export function discoverySourceInfoRows(source: DiscoverySourceRow): DiscoverySourceFact[] {
  const { capabilities } = source;
  const storage = source.kind === "storage";
  const rows: (DiscoverySourceFact | null)[] = [
    { label: "Provider", value: DISCOVERY_PROVIDER_LABEL[source.provider] ?? source.provider },
    source.baseUrl ? { label: "Endpoint", value: source.baseUrl } : null,
    storage ? { label: "Resources", value: String(source.resources?.length ?? 0) } : null,
    source.homepage
      ? {
          label: "Homepage",
          value: (
            <a href={source.homepage} target="_blank" rel="noreferrer noopener">
              {new URL(source.homepage).host} ↗
            </a>
          ),
        }
      : null,
    source.license ? { label: "Licence", value: source.license } : null,
    { label: "Search", value: capabilities.search ? "Yes" : "Link only" },
    {
      label: "Formats",
      value: capabilities.formats.map((f) => f.toUpperCase()).join(", ") || "None",
    },
    // A folder is read from this machine, so no download ceiling applies.
    source.provider === "folder"
      ? null
      : { label: "Max download", value: bytesLabel(capabilities.maxDownloadBytes) },
  ];
  return rows.filter((row): row is DiscoverySourceFact => row != null);
}

/** The Access list, or an empty one for a source that takes no token. */
export function discoverySourceAccessItems(source: DiscoverySourceRow): React.ReactNode[] {
  const { auth } = source;
  if (!auth.usesToken) return [];
  return [
    <li key="mode">
      {auth.required
        ? "This portal will not answer without a token."
        : "Works without a token; one raises the rate limit."}
    </li>,
    <li key="slot">
      Credential: <code>{auth.secretId}</code>
      {auth.present ? " (set on your account)" : " (not set)"}{" "}
      {auth.secretId ? (
        <button
          type="button"
          className={browseStyles.linkButton}
          onClick={() => requestSourceKey(auth.secretId as string)}
        >
          {auth.present ? "Change it in API Settings" : "Add yours in API Settings"}
        </button>
      ) : null}
    </li>,
    auth.helpUrl ? (
      <li key="help">
        <a href={auth.helpUrl} target="_blank" rel="noreferrer noopener">
          How to get one ↗
        </a>
      </li>
    ) : null,
  ].filter(Boolean) as React.ReactNode[];
}

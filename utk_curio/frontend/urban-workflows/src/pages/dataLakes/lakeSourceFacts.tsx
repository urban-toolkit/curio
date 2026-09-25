import React from "react";

import { LAKE_PROVIDER_LABEL, type LakeSourceRow } from "../../services/dataLakeCatalog";

/**
 * What the Data Lake Catalog says about one source, for its drawer and its
 * details modal alike.
 *
 * Both render these rows, so the two views cannot disagree about a portal the
 * way the three catalogs' hand-assembled drawers once disagreed about
 * "Published". Each view lays them out in its own container.
 */

export interface LakeSourceFact {
  label: string;
  value: React.ReactNode;
}

function bytesLabel(bytes: number): string {
  const mb = bytes / (1024 * 1024);
  return mb >= 1 ? `${Math.round(mb)} MB` : `${Math.round(bytes / 1024)} KB`;
}

export function lakeSourceInfoRows(source: LakeSourceRow): LakeSourceFact[] {
  const { capabilities } = source;
  const rows: (LakeSourceFact | null)[] = [
    { label: "Provider", value: LAKE_PROVIDER_LABEL[source.provider] ?? source.provider },
    source.baseUrl ? { label: "Endpoint", value: source.baseUrl } : null,
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
    { label: "Max download", value: bytesLabel(capabilities.maxDownloadBytes) },
  ];
  return rows.filter((row): row is LakeSourceFact => row != null);
}

/** The Access list, or an empty one for a source that takes no token. */
export function lakeSourceAccessItems(source: LakeSourceRow): React.ReactNode[] {
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
      {auth.present ? " (set on your account)" : " (not set)"}
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

import React, { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { CatalogKindIcon } from "../../components/catalog/CatalogKindVisuals";
import {
  useLakeCatalog,
  type LakeAuthMode,
  type LakeProviderType,
  type LakeSourceRow,
} from "../../services/dataLakeCatalog";
import { AUTH_FILTERS, PROVIDER_FILTERS } from "./dataLakeBrowseConstants";
import { DataLakeSourceCard } from "./DataLakeSourceCard";
import { DataLakeCatalogBrowseDrawer } from "./DataLakeCatalogBrowseDrawer";
import browseStyles from "../catalog/CatalogBrowseLayout.module.css";

type SortMode = "name" | "provider";

/**
 * The account-scope Data Lake Catalog under `/catalog/lakes`.
 *
 * The fourth peer of `/catalog/nodes`, `/catalog/data` and `/catalog/agents`:
 * same three-column grid from `CatalogBrowseLayout.module.css`, same header
 * anatomy (crumb, kind icon + h1 + count, intro, search), same filter bar, same
 * card grid, same right-hand detail drawer.
 *
 * What differs is the UNIT. The other three list things you can put on a
 * canvas; this lists *portals*, and the datasets inside one are discovered
 * live on its own page. So a card's action is "browse", not "add" - nothing
 * here is installed, and a source is not droppable.
 *
 * Every route this page calls is served from disk, so it renders in full on a
 * deployment with no outbound network at all.
 */
export const DataLakeCatalogBrowse: React.FC = () => {
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [provider, setProvider] = useState<LakeProviderType | "">("");
  const [auth, setAuth] = useState<LakeAuthMode | "">("");
  const [sort, setSort] = useState<SortMode>("name");
  const [selectedDir, setSelectedDir] = useState<string | null>(null);
  const [drawerSlotOpen, setDrawerSlotOpen] = useState(false);

  // Filtering server-side keeps one implementation of "does this match?", so
  // the chips and the search box cannot disagree with each other the way two
  // filter surfaces on one page otherwise do.
  const { data, loading, error, reload } = useLakeCatalog({ q: search, provider, auth });

  const sources = useMemo(() => {
    const rows = [...data.sources];
    if (sort === "provider") {
      rows.sort((a, b) => a.provider.localeCompare(b.provider) || a.name.localeCompare(b.name));
    }
    return rows;
  }, [data.sources, sort]);

  const selected = useMemo(
    () => sources.find((s) => s.dirName === selectedDir) ?? null,
    [sources, selectedDir]
  );

  const openSource = (source: LakeSourceRow) =>
    navigate(`/catalog/lakes/${encodeURIComponent(source.dirName)}`);

  const providerCounts = data.facets.provider ?? {};
  const authCounts = data.facets.auth ?? {};
  const total = Object.values(providerCounts).reduce((a, b) => a + b, 0);

  return (
    <div
      className={[browseStyles.page, drawerSlotOpen ? browseStyles.pageWithDrawer : ""]
        .filter(Boolean)
        .join(" ")}
    >
      <aside className={browseStyles.categoryRail}>
        <p className={browseStyles.railLabel}>By provider</p>
        <button
          className={`${browseStyles.railButton} ${provider === "" ? browseStyles.railButtonActive : ""}`}
          type="button"
          onClick={() => setProvider("")}
        >
          <span>All portals</span>
          <span className={browseStyles.railCountBadge}>{total}</span>
        </button>
        {PROVIDER_FILTERS.map(({ value, label }) => (
          <button
            key={value}
            className={`${browseStyles.railButton} ${provider === value ? browseStyles.railButtonActive : ""}`}
            type="button"
            onClick={() => setProvider((prev) => (prev === value ? "" : value))}
          >
            <span>{label}</span>
            <span className={browseStyles.railCount}>{providerCounts[value] ?? 0}</span>
          </button>
        ))}

        <div className={browseStyles.railDivider} />
        <p className={browseStyles.railLabel}>By access</p>
        {AUTH_FILTERS.map(({ value, label }) => (
          <button
            key={value}
            className={`${browseStyles.railButton} ${auth === value ? browseStyles.railButtonActive : ""}`}
            type="button"
            onClick={() => setAuth((prev) => (prev === value ? "" : value))}
          >
            <span>{label}</span>
            <span className={browseStyles.railCount}>{authCounts[value] ?? 0}</span>
          </button>
        ))}
      </aside>

      <main className={browseStyles.browseMain}>
        <section className={browseStyles.browseHeader}>
          <p className={browseStyles.crumb}>Data Lake Catalog</p>
          <div className={browseStyles.titleRow}>
            <CatalogKindIcon kind="lake" size="md" title="Data lake catalog" />
            <h1>Data Lake Catalog</h1>
            <span className={browseStyles.titleCount}>{sources.length}</span>
          </div>
          <p className={browseStyles.pageIntro}>
            Data portals and lakes this deployment can reach. Open one to search it, then
            download what you need into your <strong>Data Catalog</strong>, where it
            behaves like any other dataset.
          </p>
          <div className={browseStyles.headerTools}>
            <input
              className={browseStyles.hubSearch}
              type="search"
              placeholder="Search portals…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
        </section>

        <div className={browseStyles.filterBar}>
          <button
            className={`${browseStyles.chip} ${provider === "" && auth === "" ? browseStyles.chipActive : ""}`}
            type="button"
            onClick={() => {
              setProvider("");
              setAuth("");
            }}
          >
            All
          </button>
          {PROVIDER_FILTERS.map(({ value, label }) => (
            <button
              key={value}
              className={`${browseStyles.chip} ${provider === value ? browseStyles.chipActive : ""}`}
              type="button"
              onClick={() => setProvider((prev) => (prev === value ? "" : value))}
            >
              {/* One dot colour for every portal: on this page every card IS a
                  portal, so a per-provider hue would carry no information. See
                  --curio-kind-lake-fg. */}
              <span className={`${browseStyles.chipDot} ${browseStyles.chipDotDefault}`} />
              {label}
            </button>
          ))}
          <span className={browseStyles.filterSpacer} />
          <select
            className={browseStyles.sortSelect}
            value={sort}
            onChange={(e) => setSort(e.target.value as SortMode)}
          >
            <option value="name">Sort: Name</option>
            <option value="provider">Sort: Provider</option>
          </select>
        </div>

        {error ? (
          <div className={browseStyles.browseBanner} role="alert">
            <span>{error}</span>
            <button
              type="button"
              className={browseStyles.browseBannerDismiss}
              aria-label="Retry"
              onClick={reload}
            >
              ↻
            </button>
          </div>
        ) : null}

        {!loading && sources.length === 0 ? (
          <div className={browseStyles.empty}>
            {search || provider || auth
              ? "No portal matches those filters."
              : "This deployment has no data lake sources configured."}
          </div>
        ) : (
          <div
            className={[browseStyles.cardGrid, loading ? browseStyles.cardGridRefreshing : ""]
              .filter(Boolean)
              .join(" ")}
          >
            {sources.map((source) => (
              <DataLakeSourceCard
                key={source.dirName}
                source={source}
                selected={selectedDir === source.dirName}
                onSelect={() => setSelectedDir(source.dirName)}
                onBrowse={() => openSource(source)}
              />
            ))}
          </div>
        )}
      </main>

      <DataLakeCatalogBrowseDrawer
        source={selected}
        onBrowse={openSource}
        onClose={() => setSelectedDir(null)}
        onLayoutChange={setDrawerSlotOpen}
      />
    </div>
  );
};

export default DataLakeCatalogBrowse;

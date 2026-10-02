import React, { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { CatalogKindIcon } from "../../components/catalog/CatalogKindVisuals";
import { CardContextMenu } from "../../components/catalog/CardContextMenu";
import {
  modelCardActions,
  type CatalogCardActionId,
} from "../../components/catalog/catalogCardActions";
import ConfirmDialog from "../../components/ConfirmDialog";
import { ModelDetailModal } from "../../components/models/catalog/ModelDetailModal";
import { useModelDelete } from "../../components/models/catalog/useModelDelete";
import { useToastContext } from "../../providers/ToastProvider";
import {
  MODEL_SORT_OPTIONS,
  isDeletableModel,
  sortModels,
  useModelCatalog,
  type ModelOrigin,
  type ModelRow,
  type ModelRuntime,
  type ModelSortMode,
} from "../../services/modelCatalog";
import { ORIGIN_FILTERS, RUNTIME_FILTERS } from "./modelBrowseConstants";
import { ModelCatalogBrowseCard } from "./ModelCatalogBrowseCard";
import { ModelCatalogBrowseDrawer } from "./ModelCatalogBrowseDrawer";
import browseStyles from "../catalog/CatalogBrowseLayout.module.css";

/**
 * The account-scope Model Catalog under `/catalog/models`.
 *
 * The fifth peer of `/catalog/nodes`, `/catalog/data`, `/catalog/agents` and
 * `/catalog/discovery`: the same three-column grid from
 * `CatalogBrowseLayout.module.css`, the same header anatomy, filter bar, card
 * grid, right-hand drawer, right-click menu and details modal.
 *
 * What differs is how a model is used. It is not added to a project: a node
 * names it in its code, and dragging a model from a dataflow's Model Catalog
 * onto such a node sets that name. So this page reads and deletes; it does not
 * install. `/catalog/models/<id>` is this page with that model's details open.
 */
export const ModelCatalogBrowse: React.FC = () => {
  const navigate = useNavigate();
  const { showToast } = useToastContext();
  const [search, setSearch] = useState("");
  const [runtime, setRuntime] = useState<ModelRuntime | "">("");
  const [origin, setOrigin] = useState<ModelOrigin | "">("");
  const [sort, setSort] = useState<ModelSortMode>("shipped");
  // The peers' tri-state: undefined follows the first card, so the drawer is
  // open on arrival; null is the user having closed it.
  const [selectedId, setSelectedId] = useState<string | null | undefined>(undefined);
  // Its own state, not `selectedId`: the card click drives the drawer and
  // "View details" opens the modal (#189).
  const [detailId, setDetailId] = useState<string | null>(null);
  const [contextMenu, setContextMenu] = useState<{
    x: number;
    y: number;
    model: ModelRow;
  } | null>(null);
  const [drawerSlotOpen, setDrawerSlotOpen] = useState(false);

  // A link to a model lands where every "View details" does.
  const { modelId: linkedModelId } = useParams<{ modelId?: string }>();
  useEffect(() => {
    if (linkedModelId) setDetailId(decodeURIComponent(linkedModelId));
  }, [linkedModelId]);
  const closeDetails = () => {
    setDetailId(null);
    // Back to the plain page, so a reload does not reopen what was closed.
    if (linkedModelId) navigate("/catalog/models", { replace: true });
  };

  // The search is the server's (`?q=`); runtime and origin narrow the rows
  // here, and their counts are read off the same rows.
  const { data, loading, error, reload } = useModelCatalog({ q: search });
  const { confirmAction, requestDelete, dismissConfirm, busyId } = useModelDelete(showToast);

  const counts = useMemo(() => {
    const runtimes: Record<string, number> = {};
    const origins: Record<string, number> = {};
    for (const item of data.items) {
      runtimes[item.runtime] = (runtimes[item.runtime] ?? 0) + 1;
      origins[item.origin] = (origins[item.origin] ?? 0) + 1;
    }
    return { runtimes, origins };
  }, [data.items]);

  const models = useMemo(
    () =>
      sortModels(
        data.items.filter(
          (item) => (!runtime || item.runtime === runtime) && (!origin || item.origin === origin)
        ),
        sort
      ),
    [data.items, runtime, origin, sort]
  );

  const selected = useMemo(() => {
    if (selectedId === null) return null;
    if (selectedId !== undefined) {
      return models.find((m) => m.id === selectedId) ?? models[0] ?? null;
    }
    return models[0] ?? null;
  }, [models, selectedId]);

  // From the unfiltered rows, so the modal outlives a filter change; the modal
  // reads the model itself as well, for a link to one the search hides.
  const detailFallback = detailId ? data.items.find((m) => m.id === detailId) ?? null : null;

  const runModelAction = (id: CatalogCardActionId, model: ModelRow) => {
    switch (id) {
      case "delete":
        requestDelete(model);
        return;
      case "view-details":
        setDetailId(model.id);
        return;
      // A model is never added to or removed from a project.
      default:
        return;
    }
  };

  const filtered = Boolean(search.trim() || runtime || origin);

  return (
    <div
      className={[browseStyles.page, drawerSlotOpen ? browseStyles.pageWithDrawer : ""]
        .filter(Boolean)
        .join(" ")}
    >
      <aside className={browseStyles.categoryRail}>
        <p className={browseStyles.railLabel}>By runtime</p>
        <button
          className={`${browseStyles.railButton} ${runtime === "" ? browseStyles.railButtonActive : ""}`}
          type="button"
          onClick={() => setRuntime("")}
        >
          <span>All models</span>
          <span className={browseStyles.railCountBadge}>{data.items.length}</span>
        </button>
        {RUNTIME_FILTERS.map(({ value, label }) => (
          <button
            key={value}
            className={`${browseStyles.railButton} ${runtime === value ? browseStyles.railButtonActive : ""}`}
            type="button"
            onClick={() => setRuntime((prev) => (prev === value ? "" : value))}
          >
            <span>{label}</span>
            <span className={browseStyles.railCount}>{counts.runtimes[value] ?? 0}</span>
          </button>
        ))}

        <div className={browseStyles.railDivider} />
        <p className={browseStyles.railLabel}>By origin</p>
        {ORIGIN_FILTERS.map(({ value, label }) => (
          <button
            key={value}
            className={`${browseStyles.railButton} ${origin === value ? browseStyles.railButtonActive : ""}`}
            type="button"
            onClick={() => setOrigin((prev) => (prev === value ? "" : value))}
          >
            <span>{label}</span>
            <span className={browseStyles.railCount}>{counts.origins[value] ?? 0}</span>
          </button>
        ))}
      </aside>

      <main className={browseStyles.browseMain}>
        <section className={browseStyles.browseHeader}>
          <p className={browseStyles.crumb}>Model Catalog</p>
          <div className={browseStyles.titleRow}>
            <CatalogKindIcon kind="model" size="md" title="Model Catalog" />
            <h1>Model Catalog</h1>
            <span className={browseStyles.titleCount}>{models.length}</span>
          </div>
          <p className={browseStyles.pageIntro}>
            Trained models your nodes can run. Models you download from the{" "}
            <strong>Discovery Catalog</strong> land here too.
          </p>
          <div className={browseStyles.headerTools}>
            <input
              className={browseStyles.hubSearch}
              type="search"
              placeholder="Search models…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              aria-label="Search models"
            />
          </div>
        </section>

        <div className={browseStyles.filterBar} data-curio-catalog-filter-bar="true">
          <button
            className={`${browseStyles.chip} ${runtime === "" && origin === "" ? browseStyles.chipActive : ""}`}
            type="button"
            onClick={() => {
              setRuntime("");
              setOrigin("");
            }}
          >
            All
          </button>
          {RUNTIME_FILTERS.map(({ value, label }) => (
            <button
              key={value}
              data-curio-runtime-chip={value}
              className={`${browseStyles.chip} ${runtime === value ? browseStyles.chipActive : ""}`}
              type="button"
              onClick={() => setRuntime((prev) => (prev === value ? "" : value))}
            >
              {/* One dot colour for every runtime: on this page every card IS a
                  model, so a per-runtime hue would carry no information. See
                  --curio-kind-model-fg. */}
              <span className={`${browseStyles.chipDot} ${browseStyles.chipDotDefault}`} />
              {label}
            </button>
          ))}
          {ORIGIN_FILTERS.map(({ value, label }) => (
            <button
              key={value}
              data-curio-origin-chip={value}
              className={`${browseStyles.chip} ${origin === value ? browseStyles.chipActive : ""}`}
              type="button"
              onClick={() => setOrigin((prev) => (prev === value ? "" : value))}
            >
              {label}
            </button>
          ))}
          <span className={browseStyles.filterSpacer} />
          <select
            className={browseStyles.sortSelect}
            value={sort}
            aria-label="Sort models"
            onChange={(e) => setSort(e.target.value as ModelSortMode)}
          >
            {MODEL_SORT_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
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

        {loading && data.items.length === 0 ? (
          <div className={browseStyles.empty}>Loading models…</div>
        ) : !loading && !error && models.length === 0 ? (
          <div className={browseStyles.empty}>
            {filtered ? "No models match the current filters." : "Your Model Catalog is empty."}
          </div>
        ) : (
          <div
            className={[browseStyles.cardGrid, loading ? browseStyles.cardGridRefreshing : ""]
              .filter(Boolean)
              .join(" ")}
          >
            {models.map((model) => (
              <ModelCatalogBrowseCard
                key={`${model.origin}:${model.id}`}
                model={model}
                selected={selected?.id === model.id}
                onSelect={() => setSelectedId(model.id)}
                onViewDetails={() => setDetailId(model.id)}
                onContextMenu={(e) => {
                  e.preventDefault();
                  // Select first, as the peer pages do: the menu acts on this
                  // model, so the drawer should not describe another one.
                  setSelectedId(model.id);
                  setContextMenu({ x: e.clientX, y: e.clientY, model });
                }}
              />
            ))}
          </div>
        )}
      </main>

      <ModelCatalogBrowseDrawer
        model={selected}
        deletingId={busyId}
        onDelete={requestDelete}
        onViewDetails={(model) => setDetailId(model.id)}
        onClose={() => setSelectedId(null)}
        onLayoutChange={setDrawerSlotOpen}
      />

      {contextMenu ? (
        <CardContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          ariaLabel="Model actions"
          items={modelCardActions({ deletable: isDeletableModel(contextMenu.model) })}
          onSelect={(id) => runModelAction(id as CatalogCardActionId, contextMenu.model)}
          onDismiss={() => setContextMenu(null)}
        />
      ) : null}

      {detailId ? (
        <ModelDetailModal
          key={detailId}
          modelId={detailId}
          fallbackModel={detailFallback}
          onClose={closeDetails}
        />
      ) : null}

      {confirmAction ? (
        <ConfirmDialog
          title={confirmAction.title}
          body={confirmAction.body}
          confirmLabel={confirmAction.confirmLabel}
          destructive={confirmAction.destructive}
          onCancel={dismissConfirm}
          onConfirm={() => {
            const { run } = confirmAction;
            dismissConfirm();
            void run();
          }}
        />
      ) : null}
    </div>
  );
};

export default ModelCatalogBrowse;

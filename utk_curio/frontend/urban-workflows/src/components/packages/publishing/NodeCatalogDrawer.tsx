import React, { useCallback, useEffect, useMemo, useState, useRef } from "react";
import { refreshPackageRegistry } from "../../../registry/packageRegistryBootstrap";
import { useFlowContext } from "../../../providers/FlowProvider";
import { BUILTIN_PACKAGE_ID } from "../../../registry/packageKeys";
import { useToastContext } from "../../../providers/ToastProvider";
import {
  applyProjectLockfile,
  getPackagesRevision,
  setCurrentProjectPackages,
} from "../../../registry/projectPackagesStore";
import {
  catalogAndOwnPackages,
  isNewerPackageVersion,
  matchesSearch,
  nodesNamingModelInCodeOnly,
  packagesApi,
  restartNotice,
  sortPackages,
  usePackageAddRequests,
  usePackageCatalog,
  withRestartNotice,
} from "../../../services/packages";
import { codeOnlyDataflows, codeOnlyWarning } from "../../../services/codeOnlyUsage";
import type {
  DrawerTab,
  PackageAddRequest,
  PackageKind,
  PackagePayload,
  ProjectSaveAction,
  SortMode,
} from "../../../services/packages";
import { hostedGuestSignInNote, useHostedGuest } from "../../apiSettings/useHostedGuest";
import type { CatalogItemKind } from "../../catalog/CatalogKindVisuals";
import { InstallPermissionsDialog } from "./InstallPermissionsDialog";
import { DrawerHeader } from "./DrawerHeader";
import { DrawerTabs } from "./DrawerTabs";
import { usePackageArchiveImport } from "../../../providers/packages/usePackageArchiveImport";
import { PackageDetailModal } from "./PackageDetailModal";
import { PackageSearchRow } from "./PackageSearchRow";
import { PackageCard } from "./PackageCard";
import { EnvNote } from "./EnvNote";
import { DrawerFooter } from "./DrawerFooter";
import footerStyles from "./DrawerFooter.module.css";
import { NodeFromFunctionModal } from "../editing/NodeFromFunctionModal";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faFileCode } from "@fortawesome/free-solid-svg-icons";
import shell from "./CatalogDrawerShell.module.css";
import { useDrawerDragThrough } from "./useDrawerDragThrough";
import styles from "./NodeCatalogDrawer.module.css";
import { modalStackDepth } from "../../ModalShell";
import ConfirmDialog from "../../ConfirmDialog";
import { EditorRequestsSection } from "../../catalog/EditorRequestsSection";
import { useAskForPackage } from "../../collab/useAskTheOwner";
import { useAgentsDataflowId } from "../../../providers/agents";


export interface NodeCatalogDrawerProps {
  /** When true, scrim fades in and the panel slides in from the right. */
  presented: boolean;
  onRequestClose: () => void;
  /** Called once the exit transition finishes (or immediately when motion is reduced). */
  onExitComplete: () => void;
  /** Seeds the search box on open, so a caller that already knows which
   *  package the user needs can land them on it (#233). */
  initialSearch?: string;
  /** Which catalog this drawer is: the Node Catalog (`node`, the default) or
   *  the Model Catalog (`model`), the same drawer over model packages. */
  packageKind?: PackageKind;
}

const BUILTIN_PACKAGE_DIR = `${BUILTIN_PACKAGE_ID}@1`;

/** What each catalog's drawer says; everything else is the same drawer. */
const DRAWER_COPY: Record<PackageKind, {
  title: string;
  titleId: string;
  subtitle: string;
  kindIcon: CatalogItemKind;
  rootAttribute: string;
  searchPlaceholder?: string;
  sortAriaLabel?: string;
  noneInProject: string;
  noneMatch: string;
  /** What it lists, as an Add, Remove or Import names it. */
  items: string;
}> = {
  node: {
    title: "Node Catalog",
    titleId: "node-catalog-drawer-title",
    subtitle: "Node packages available in this project.",
    kindIcon: "package",
    rootAttribute: "data-curio-node-catalog-drawer",
    noneInProject: "No packages added to this project yet.",
    noneMatch: "No packages match the current filters.",
    items: "packages",
  },
  model: {
    title: "Model Catalog",
    titleId: "model-catalog-title",
    subtitle: "Model packages available in this project. Drag a model onto the canvas to add its node, or onto a node to swap its model.",
    kindIcon: "model",
    rootAttribute: "data-curio-model-catalog-drawer",
    searchPlaceholder: "Search models, publishers, tags…",
    sortAriaLabel: "Sort models",
    noneInProject: "No models added to this project yet.",
    noneMatch: "No models match the current filters.",
    items: "models",
  },
};

/**
 * The in-canvas Node Catalog drawer (memo dev/143, F4): a rendering surface over
 * THE catalog hook. Its catalog state — listing, the install review, install /
 * uninstall, busy keys, the error banner, the restart notice — lives in
 * `usePackageCatalog({ kind: "project" })`, shared with the Node Catalog page;
 * this file keeps only presentation state (tab, search, sort, pin, the detail
 * modal and the confirmation slot) and the render tree, which is unchanged.
 *
 * The Model Catalog drawer is this drawer with `packageKind="model"`: the same
 * tabs, Add, Remove, Import, details and restart notice, over model packages.
 */
export const NodeCatalogDrawer: React.FC<NodeCatalogDrawerProps> = ({
  presented,
  onRequestClose,
  onExitComplete,
  initialSearch = "",
  packageKind = "node",
}) => {
  const copy = DRAWER_COPY[packageKind];
  const drawerRef = useRef<HTMLElement>(null);
  const dragThrough = useDrawerDragThrough();

  // The drawer is *per-project*: Install/Uninstall write to the current
  // project's lockfile (see docs/NODE-CATALOG.md).
  const {
    projectId, projectName, packages: projectPackages, ensureProjectId: keepDataflow, projectDirty, whenChangesKept, nodes,
  } = useFlowContext();
  const { showToast } = useToastContext();
  const hostedGuest = useHostedGuest();

  const [tab, setTab] = useState<DrawerTab>("browse");
  const [detailPkg, setDetailPkg] = useState<PackagePayload | null>(null);
  const [search, setSearch] = useState(initialSearch);
  const [sort, setSort] = useState<SortMode>("new");
  const [pinned, setPinned] = useState(false);
  const [functionOpen, setFunctionOpen] = useState(false);
  // One slot for whichever confirmation is open (#197). The two destructive
  // actions here are mutually exclusive from the user's point of view, and a
  // single slot keeps the "what am I confirming" state next to the copy.
  const [confirmAction, setConfirmAction] = useState<{
    title: string; body: string; confirmLabel: string; run: () => Promise<void>; destructive?: boolean;
  } | null>(null);

  /**
   * A dataflow is created on its FIRST SAVE, so every lockfile write (Install,
   * Remove, Import) makes it first when there is no id (#220); the hook owns
   * the sequencing and reports a refusal. Mirrors ``useDatasetCatalogDrawer``.
   * One create at a time: beside one already out (after a run) it would make
   * a second dataflow. A hosted guest cannot save one, so it is told to sign
   * in instead, in the words of the action that asked.
   */
  const onEnsureProject = useCallback(async (action: ProjectSaveAction = "add") => {
    if (hostedGuest) {
      showToast(hostedGuestSignInNote(`${action} ${copy.items}`), "warning");
      return null;
    }
    return keepDataflow();
  }, [keepDataflow, hostedGuest, showToast, copy.items]);

  /** memo dev/101: when the backend's lockfile differs from the mirror, the
   *  palette/registry must follow — not only the drawer's pill. */
  const onProjectLockfile = useCallback(async (packages: string[], token: unknown) => {
    if (applyProjectLockfile(packages, token as number)) {
      await refreshPackageRegistry();
    }
  }, []);

  // On the owner's dataflow, an invited editor's Add of a package or a model
  // asks her to add it (`useAskForPackage`): her review applies it. A card he
  // drops on her canvas asks her too, and makes its node at once
  // (`usePackageCardDrop`). His Remove from project takes a package out of
  // her dataflow as his own change, and deletes it from no account.
  const askForPackage = useAskForPackage();
  const openedDataflowId = useAgentsDataflowId();

  const {
    installed, catalogByDir, catalog, catalogPublishedDirs, busy, cardActionDir, actionError, restartNoticeText,
    installCandidate, installMode, conflictReport, effectiveProjectId, ensureProjectId, kindOfDir,
    reload, reportActionError, dismissActionError, dismissRestartNotice,
    probeInstall: onInstall,
    probeUpdate: onUpdate,
    confirmInstall: confirmCatalogInstall,
    cancelInstall,
    uninstallFromProject: performUninstall,
  } = usePackageCatalog({
    scope: { kind: "project", projectId },
    packageKind,
    showToast,
    onEnsureProject,
    beforeReload: getPackagesRevision,
    onProjectLockfile,
    onInstalledToProject: setCurrentProjectPackages,
    refreshRegistry: refreshPackageRegistry,
    logLabel: "NodeCatalogDrawer",
    editorsDataflowId: askForPackage ? openedDataflowId : null,
  });

  const onAdd = useCallback((pkg: PackagePayload) => {
    if (!askForPackage) {
      void onInstall(pkg);
      return;
    }
    setConfirmAction({
      title: `Ask to add ${pkg.name}?`,
      body: `Ask the dataflow's owner to add ${pkg.name} to this dataflow? It is added once the owner applies your request.`,
      confirmLabel: "Ask the owner",
      destructive: false,
      run: async () => {
        await askForPackage({ dirName: pkg.dirName, name: pkg.name }, { add: true });
      },
    });
  }, [askForPackage, onInstall]);

  /** dirNames the current project has declared in its lockfile. Drives the
   * Install vs Uninstall affordance per card. */
  const projectInstalledDirs = useMemo(
    // Follows the ONE lockfile store in every case: ``ProjectLoader`` seeds an
    // unsaved dataflow's scope from the account defaults, so this never fetches
    // them itself (that made the drawer a second source of truth that could
    // disagree with the palette). The builtin package is added unconditionally,
    // as the palette filter does (``inDataflowScope``): it is in every dataflow
    // by construction, so its absence can only mean "the lockfile has not
    // arrived yet", which used to render an "Add" button for something present
    // and un-removable.
    //
    // The lockfile names packages of both kinds; each drawer counts and lists
    // its own (a package neither listing knows is a node package, the
    // manifest's default).
    () => new Set(
      [...projectPackages, BUILTIN_PACKAGE_DIR].filter((dirName) => kindOfDir(dirName) === packageKind),
    ),
    [projectPackages, kindOfDir, packageKind],
  );

  /** dirNames in the user store (for the "Installed" tab listing + update detection). */
  const userStoreDirs = useMemo(
    () => new Set(installed.map((p) => p.dirName)),
    [installed],
  );

  useEffect(() => {
    if (!presented) return;
    drawerRef.current?.focus();
  }, [presented]);

  const handleDrawerTransitionEnd = useCallback(
    (e: React.TransitionEvent<HTMLElement>) => {
      if (e.target !== drawerRef.current) return;
      if (e.propertyName !== "transform") return;
      if (presented) return;
      onExitComplete();
    },
    [onExitComplete, presented],
  );

  useEffect(() => {
    if (!presented) return;
    const onKey = (ev: KeyboardEvent) => {
      // Defer to any open modal (see ModalShell's stack).
      if (modalStackDepth() > 0) return;
      // ...and to the pin. This used to close a pinned drawer, discarding the
      // pin the user had just set - the Agent drawer already honoured it.
      if (ev.key === "Escape" && !pinned) onRequestClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [presented, pinned, onRequestClose]);

  const filteredCatalog = useMemo(
    // Browse all: the shared catalog and the account's own packages (imported,
    // published or downloaded), which no catalog lists, so any of them can be
    // added to this dataflow. The Node Catalog page lists the same rows.
    () => sortPackages(catalogAndOwnPackages(catalog, installed).filter((p) => matchesSearch(p, search)), sort),
    [catalog, installed, search, sort],
  );

  const filteredInstalled = useMemo(
    // "Installed" in the drawer = installed in THIS project, not in the user store.
    () => installed.filter(
      (p) => projectInstalledDirs.has(p.dirName) && matchesSearch(p, search),
    ),
    [installed, projectInstalledDirs, search],
  );

  // A card of this drawer dropped on the canvas, whose package the dataflow
  // has not added: the same Add as the card's button, and the node once the
  // package is added.
  const takeAddRequest = useCallback((request: PackageAddRequest) => {
    if (request.kind !== packageKind) return false;
    const pkg = catalogAndOwnPackages(catalog, installed).find((p) => p.dirName === request.dirName);
    if (!pkg) return false;
    void onInstall(pkg, { onAdded: request.onAdded });
    return true;
  }, [packageKind, catalog, installed, onInstall]);
  usePackageAddRequests(takeAddRequest, presented);

  // The shared import pathway the Node Catalog PAGE header calls too, so the
  // two surfaces cannot drift; the drawer alone has a lockfile to land it in.
  const [importBusy, setImportBusy] = useState(false);
  const [importRestartNotice, setImportRestartNotice] = useState<string | null>(null);
  const { importArchive } = usePackageArchiveImport({
    // Carries the id an auto-save minted before the prop re-rendered (#220).
    projectId: effectiveProjectId,
    reload,
    onError: reportActionError,
    onInstalledToProject: setCurrentProjectPackages,
    onImported: (_pkg, notice, restart) => {
      if (notice) showToast(withRestartNotice(notice, restart), "error");
      else if (restart?.libs?.length) setImportRestartNotice(restartNotice(restart));
    },
  });

  const onPickArchive = useCallback(
    async (file: File) => {
      // Save first, so the import lands in THIS dataflow's lockfile and not
      // only in the account store (the "not scoped to a project" half of #220).
      const intoProjectId = await ensureProjectId("Couldn't save dataflow before importing", "import");
      if (intoProjectId === null) {
        return;
      }
      // The drawer's own busy/error chrome; the shared hook owns the call.
      setImportBusy(true);
      try {
        // Hand the id over rather than letting the hook read the one it
        // captured when it rendered. When the save above is what minted it,
        // that captured value is still null and the hook skipped
        // ``installToProject`` entirely: the package landed in the account
        // store and never in this dataflow's lockfile, so it never reached
        // the palette (#340). ``performInstall`` reads the ref at call time
        // for the same reason; this path used to be the odd one out.
        await importArchive(file, intoProjectId);
      } catch (err) {
        // Every other action in this drawer reports through here; this one
        // used to have only a `finally`, so anything thrown after the upload
        // became an unhandled rejection. Both `finally` blocks then tidied the
        // UI back to its resting state, leaving a failed import that looked
        // exactly like a successful one: no toast, no error chrome, the footer
        // button back to "Import package", and the package in the account
        // store but not in the lockfile. That is unreadable for a user and it
        // is why #340 could only ever be seen as an e2e waiting out its
        // timeout on an install request nobody could prove was sent.
        reportActionError(`Couldn't import ${file.name}`, err);
      } finally {
        setImportBusy(false);
      }
    },
    [ensureProjectId, importArchive, reportActionError],
  );

  /**
   * The dataflows whose nodes name the model in their code alone, which the
   * Remove names, as the Data Catalog's names those that load a dataset in
   * code. A node that does keeps nothing: nothing rewrites node code on
   * removal, so that code stays behind. A node of the package, or one bound
   * to its model (`modelRefs`), keeps it, and the backend refuses the removal
   * while one is on this canvas.
   *
   * This dataflow is read from its canvas, which may hold edits not saved
   * yet: its lockfile entry is the one going, so its saved row would count
   * it as kept. Every other one comes from the usage read, as saved. The
   * Data Catalog's Remove names them through the same code
   * (`codeOnlyDataflows`).
   */
  const modelCodeOnlyUsers = useCallback(
    (pkg: PackagePayload): Promise<string[]> =>
      codeOnlyDataflows(
        {
          id: projectId,
          name: projectName,
          inCodeOnly: nodesNamingModelInCodeOnly(nodes ?? [], pkg.packageId).length > 0,
        },
        () => packagesApi.usage(pkg.dirName),
      ),
    [nodes, projectName, projectId],
  );

  const onUninstall = useCallback(async (pkg: PackagePayload) => {
    if (askForPackage) {
      setConfirmAction({
        title: `Remove ${pkg.name}?`,
        body: `Remove ${pkg.name} (${pkg.dirName}) from this dataflow?\n\nIt stays in the account of the dataflow's owner, and in yours.`,
        confirmLabel: "Remove",
        run: () => performUninstall(pkg),
      });
      return;
    }
    const codeWarning = codeOnlyWarning(
      packageKind === "model" ? await modelCodeOnlyUsers(pkg) : [],
      "model",
      () => "That code is left as it is, and fails once the model leaves your account.",
    );
    // No `projectId` guard: an unsaved dataflow saves itself on confirm (the
    // hook's ``uninstallFromProject``). Guarding here hid the action entirely.
    setConfirmAction({
      title: `Remove ${pkg.name}?`,
      // The second paragraph states the condition rather than guessing the
      // outcome: `prune_unreferenced_packages` deletes the store copy, drops it
      // from defaults and pip-uninstalls its libraries from the SHARED
      // interpreter, but only when no other dataflow's lockfile still names it.
      body:
        `Remove ${pkg.name} (${pkg.dirName}) from this project?` +
        `\n\nIf no other dataflow uses it, it is also deleted from your account ` +
        `and its Python libraries are uninstalled from the shared environment, ` +
        `which affects every dataflow and everyone using this Curio.` +
        codeWarning,
      confirmLabel: "Remove",
      run: () => performUninstall(pkg),
    });
  }, [askForPackage, packageKind, modelCodeOnlyUsers, performUninstall]);

  const anyBusy = busy || importBusy;
  // dev/92 B-2: the restart-honesty line (backend-declared, never inferred) from
  // a project install (the hook) or from a sideload (this surface's import path).
  const noticeText = restartNoticeText ?? importRestartNotice;
  const dismissNotice = () => {
    dismissRestartNotice();
    setImportRestartNotice(null);
  };

  return (
    <>
      <div
        className={`${shell.overlayRoot} ${styles.overlayRoot} ${
          presented ? shell.overlayRootPresented : ""
        }`}
        // The drawer stays mounted through its exit slide, and the panel below
        // carries aria-modal="true" - so without this it advertises a modal
        // dialog to assistive tech while sliding away. Its two siblings
        // (DatasetCatalogDrawer, AgentCatalogDrawer) have always had it.
        aria-hidden={!presented}
        {...{ [copy.rootAttribute]: "true" }}
        {...dragThrough}
      >
        <button
          type="button"
          className={shell.scrim}
          aria-label={`Close ${copy.title} drawer`}
          onClick={() => {
            if (!pinned) onRequestClose();
          }}
        />
        <aside
          ref={drawerRef}
          className={shell.drawer}
          role="dialog"
          aria-modal="true"
          aria-labelledby={copy.titleId}
          tabIndex={-1}
          onTransitionEnd={handleDrawerTransitionEnd}
        >
          <DrawerHeader
            pinned={pinned}
            onPinToggle={() => setPinned((v) => !v)}
            onClose={onRequestClose}
            kind={copy.kindIcon}
            title={copy.title}
            titleId={copy.titleId}
            subtitle={copy.subtitle}
            closeAriaLabel={`Close ${copy.title} drawer`}
          />

          <PackageSearchRow
            search={search}
            sort={sort}
            onSearchChange={setSearch}
            onSortChange={(value) => setSort(value as SortMode)}
            placeholder={copy.searchPlaceholder}
            sortAriaLabel={copy.sortAriaLabel}
          />

          <DrawerTabs
            tab={tab}
            installedCount={projectInstalledDirs.size}
            onChange={setTab}
          />

          <div className={shell.scrollBody}>
            {/* What the dataflow's editors asked its owner to add, of this
                catalog's kind, which she reviews here: nothing while no
                request waits. */}
            <EditorRequestsSection catalog={packageKind} />
            {noticeText ? (
              <div className={styles.noticeBanner} role="status">
                <span className={styles.errorBannerText}>{noticeText}</span>
                <button
                  type="button"
                  className={styles.noticeBannerDismiss}
                  aria-label="Dismiss restart notice"
                  onClick={dismissNotice}
                >
                  ×
                </button>
              </div>
            ) : null}
            {actionError ? (
              <div className={shell.errorBanner} role="alert">
                <span className={shell.errorBannerText}>{actionError}</span>
                <button
                  type="button"
                  className={shell.errorBannerDismiss}
                  aria-label="Dismiss error"
                  onClick={dismissActionError}
                >
                  ×
                </button>
              </div>
            ) : null}
            {tab === "installed" ? (
              filteredInstalled.length === 0 ? (
                <div className={shell.empty}>
                  {projectInstalledDirs.size === 0 ? copy.noneInProject : copy.noneMatch}
                </div>
              ) : (
                /* The SAME card as the Browse tab next door, in the same card
                   list. This tab rendered `MyPackagesList` - a compact
                   dot-and-row list with its own actions - so one drawer showed
                   its two tabs in two visual languages, and neither matched the
                   Data or Agent drawer, which use one card in both of theirs. */
                <div className={shell.cardList}>
                  {filteredInstalled.map((pkg) => (
                    <PackageCard
                      key={pkg.dirName}
                      pkg={pkg}
                      isInstalled
                      hasUpdate={
                        catalogByDir.get(pkg.dirName) != null
                        && isNewerPackageVersion(catalogByDir.get(pkg.dirName)!.version, pkg.version)
                      }
                      catalogRow={catalogByDir.get(pkg.dirName)}
                      busy={anyBusy}
                      cardActionDir={cardActionDir}
                      onOpenDetails={setDetailPkg}
                      onInstall={(p) => onAdd(p)}
                      onUpdate={(p) => void onUpdate(p)}
                      onUninstall={(p) => onUninstall(p)}
                      hasProject={Boolean(projectId)}
                    />
                  ))}
                </div>
              )
            ) : (
              <>
                {filteredCatalog.length === 0 ? (
                  <div className={shell.empty}>{copy.noneMatch}</div>
                ) : (
                  <div className={shell.cardList}>
                    {filteredCatalog.map((pkg) => {
                      // "Installed" in the drawer means "in this project's
                      // lockfile" — the user-store presence is irrelevant
                      // for the per-project surface. The one exception is
                      // ``curio.builtin@*``: it ships with every Curio
                      // instance and can't be uninstalled, so it's always
                      // "installed" regardless of what the lockfile says
                      // (which matters for unsaved /dataflow/new dataflows
                      // and for legacy projects saved before the lockfile
                      // contract included it).
                      const isBuiltin = pkg.dirName.startsWith("curio.builtin@");
                      const isInstalled = isBuiltin || projectInstalledDirs.has(pkg.dirName);
                      const catalogRow = catalogByDir.get(pkg.dirName);
                      const userStoreRow = userStoreDirs.has(pkg.dirName)
                        ? installed.find((r) => r.dirName === pkg.dirName)
                        : undefined;
                      const hasUpdate =
                        isInstalled
                        && userStoreRow != null
                        && catalogRow != null
                        && isNewerPackageVersion(catalogRow.version, userStoreRow.version);
                      return (
                        <PackageCard
                          key={pkg.dirName}
                          pkg={pkg}
                          isInstalled={isInstalled}
                          hasUpdate={hasUpdate}
                          catalogRow={catalogRow}
                          busy={anyBusy}
                          cardActionDir={cardActionDir}
                          // No publish/unpublish here: account-level decisions
                          // live in the Node Catalog page's detail drawer.
                          onOpenDetails={setDetailPkg}
                          onInstall={(p) => onAdd(p)}
                          onUpdate={(p) => void onUpdate(p)}
                          onUninstall={(p) => onUninstall(p)}
                          hasProject={Boolean(projectId)}
                        />
                      );
                    })}
                  </div>
                )}
              </>
            )}

            <EnvNote />
          </div>

          <DrawerFooter
            busy={anyBusy}
            onSideload={(file) => void onPickArchive(file)}
          >
            {/* A node, not a model, is written from a Python function. */}
            {packageKind === "node" ? (
              <button
                type="button"
                className={footerStyles.footerGhost}
                disabled={anyBusy}
                onClick={() => setFunctionOpen(true)}
              >
                <FontAwesomeIcon icon={faFileCode} aria-hidden /> New node from a Python function
              </button>
            ) : null}
          </DrawerFooter>
        </aside>
      </div>

      {packageKind === "node" ? (
        <NodeFromFunctionModal
          show={functionOpen}
          onClose={() => setFunctionOpen(false)}
          onSaved={() => void reload()}
        />
      ) : null}

      {/* The card's "View details". The Node Catalog was the only one of the
          three with no detail view anywhere; `PackageDetailModal` is that view,
          and it shows the FULL node list where this drawer caps it. */}
      {detailPkg ? (
        <PackageDetailModal
          pkg={detailPkg}
          isPublished={catalogPublishedDirs.has(detailPkg.dirName)}
          unsavedChanges={projectDirty}
          whenChangesKept={whenChangesKept}
          onClose={() => setDetailPkg(null)}
        />
      ) : null}

      {installCandidate ? (
        <InstallPermissionsDialog
          pkg={installCandidate}
          conflicts={conflictReport ?? []}
          busy={anyBusy}
          onCancel={cancelInstall}
          onConfirm={() => void confirmCatalogInstall()}
          confirmLabel={installMode === "update" ? "Update" : undefined}
          busyLabel={installMode === "update" ? "Updating…" : undefined}
        />
      ) : null}

      {confirmAction ? (
        <ConfirmDialog
          title={confirmAction.title}
          body={confirmAction.body}
          confirmLabel={confirmAction.confirmLabel}
          destructive={confirmAction.destructive ?? true}
          layer="overlay"
          onCancel={() => setConfirmAction(null)}
          onConfirm={() => {
            const { run } = confirmAction;
            setConfirmAction(null);
            void run();
          }}
        />
      ) : null}
    </>
  );
};

import React, { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { useReactFlow, useStore } from "reactflow";
import ModalShell from "../../ModalShell";
import { packagesApi, refreshPackageRegistry, triggerBlobDownload } from "../../../api/packagesApi";
import { getPaletteNodeTypes, subscribeToRegistry } from "../../../registry";
import { groupPalettePackages } from "../../menus/nodes/toolsMenuPackagePalette/model";
import { useStarterContext } from "../../../providers/StarterProvider";
import { useToastContext } from "../../../providers/ToastProvider";
import { useFlowContext } from "../../../providers/FlowProvider";
import { setCurrentProjectPackages } from "../../../registry/projectPackagesStore";
import {
  SAVE_AS_NEW_PACK,
  buildFactoryInstallEnvelope,
  buildSaveAsInstallDraft,
  canvasTemplateLabelFromNode,
  normalizeTemplateLabel,
  runtimeCodeFromRfNode,
  saveAsWouldReplaceByLabel,
} from "../../../utils/palettePackageFactoryDraft";
import { getFlowNodeCanonicalType } from "../../../utils/flowNodeCanonicalType";
import { tryGetNodeDescriptor } from "../../../registry/nodeRegistry";
import { NodeTemplateId } from "../../../registry/types";
import styles from "./NodeSaveAsModal.module.css";

const NOOP = () => () => {};

function registryBootstrapKey(): string {
  return String(getPaletteNodeTypes().length);
}

function packageLabelsForSectionKey(sectionKey: string): string[] {
  return getPaletteNodeTypes()
    .filter(
      (d) =>
        d.source === "package" &&
        d.package &&
        `${d.package.packageId}@${d.package.major}` === sectionKey,
    )
    .map((d) => d.label);
}

export function NodeSaveAsModal({
  show,
  nodeId,
  onClose,
}: {
  show: boolean;
  nodeId: string;
  onClose: () => void;
}) {
  const { setNodes } = useReactFlow();
  const { getStarters } = useStarterContext();
  const { showToast } = useToastContext();
  const { projectId } = useFlowContext();
  const [targetKey, setTargetKey] = useState<string>(SAVE_AS_NEW_PACK);
  const [newPackageName, setNewPackageName] = useState("");
  const [busy, setBusy] = useState(false);
  const [busyKind, setBusyKind] = useState<"save" | "export" | null>(null);

  const registryKey = useSyncExternalStore(
    typeof window !== "undefined" ? subscribeToRegistry : NOOP,
    registryBootstrapKey,
    () => "ssr",
  );
  void registryKey;

  const packageOptions = useMemo(() => {
    const packageTypes = getPaletteNodeTypes().filter((d) => d.source === "package");
    return groupPalettePackages(packageTypes)
      .filter((g) => g.descriptors[0]?.package?.readOnly !== true)
      .map((g) => ({
        sectionKey: g.key,
        displayName: g.descriptors[0]?.package?.name?.trim() || g.label,
      }));
  }, [registryKey]);

  // Subscribed, not sampled. The only way in here is the Node settings modal's
  // "Save as package node...", whose onSave (styles.tsx) calls updateDataNode
  // and setSaveAsOpen(true) in one batch. updateDataNode writes FlowProvider's
  // useNodesState array, which reaches React Flow's store only when its
  // prop-sync effect runs, i.e. after the render in which `show` flips true. A
  // useMemo keyed on [show, nodeId, getNodes] therefore captured the *pre-edit*
  // node and, since none of those deps ever change again, held it for the
  // modal's whole lifetime: every edit just made in Node settings was dropped
  // from the saved package. Selecting off the store fixes that and keeps the
  // draft honest if the node changes again while the modal is open.
  //
  // The `show` guard matters for cost as much as correctness: this modal is
  // rendered once per canvas node, and returning a stable null for the closed
  // ones keeps them from re-rendering on every store change.
  const canvasNode = useStore(
    useCallback(
      (s: any) => (show ? s.nodeInternals.get(nodeId) ?? null : null),
      [show, nodeId],
    ),
  );

  const nodeLabel = useMemo(() => {
    if (!canvasNode) return "Node";
    const nt = getFlowNodeCanonicalType(canvasNode);
    if (!nt) return "Node";
    const desc = tryGetNodeDescriptor(nt as NodeTemplateId);
    if (!desc) return "Node";
    return canvasTemplateLabelFromNode(canvasNode, desc);
  }, [canvasNode]);

  useEffect(() => {
    if (!show) return;
    setTargetKey(packageOptions[0]?.sectionKey ?? SAVE_AS_NEW_PACK);
    setNewPackageName(`${nodeLabel} package`);
  }, [show, nodeLabel, packageOptions]);

  const willReplace = useMemo(() => {
    if (targetKey === SAVE_AS_NEW_PACK) return false;
    const labels = packageLabelsForSectionKey(targetKey);
    const norm = normalizeTemplateLabel(nodeLabel);
    return labels.some((l) => normalizeTemplateLabel(l) === norm);
  }, [targetKey, nodeLabel, registryKey]);

  const targetPackageName = useMemo(
    () => packageOptions.find((p) => p.sectionKey === targetKey)?.displayName,
    [packageOptions, targetKey],
  );

  // Shared by Save and Export: resolve the target package and turn the canvas
  // node into a factory draft. Returns null (after toasting) when the draft
  // can't be built, so both callers can simply bail.
  const buildDraft = useCallback(async () => {
    if (!canvasNode) return null;

    let draft;
    let replace = false;
    let replacedExistingKind = false;

    if (targetKey === SAVE_AS_NEW_PACK) {
      draft = buildSaveAsInstallDraft({
        canvasNode,
        target: { kind: "new", packageDisplayName: newPackageName.trim() || undefined },
        getStarters,
      });
    } else {
      const { packages } = await packagesApi.listInstalled();
      const pkg = packages.find((p) => `${p.packageId}@${p.major}` === targetKey);
      if (!pkg) {
        showToast("Could not load the selected package.", "warning");
        return null;
      }
      replacedExistingKind = saveAsWouldReplaceByLabel(pkg, nodeLabel);
      draft = buildSaveAsInstallDraft({
        canvasNode,
        target: { kind: "installed", package: pkg },
        getStarters,
      });
      replace = true;
    }

    if (!draft) {
      showToast("Could not build a package draft from this node.", "error");
      return null;
    }
    return { draft, replace, replacedExistingKind };
  }, [canvasNode, getStarters, newPackageName, nodeLabel, showToast, targetKey]);

  const onConfirm = useCallback(async () => {
    if (!canvasNode || busy) return;
    setBusy(true);
    setBusyKind("save");
    try {
      const built = await buildDraft();
      if (!built) return;
      const { draft, replace, replacedExistingKind } = built;

      const result = await packagesApi.factoryInstall(buildFactoryInstallEnvelope(draft, replace));
      // When creating a brand-new package via Save As, the package is only in
      // the user store after factoryInstall. refreshPackageRegistry filters
      // by the project lockfile, so the new descriptor would be invisible.
      // Add it to the project lockfile first so the descriptor gets registered.
      if (targetKey === SAVE_AS_NEW_PACK && projectId) {
        const projResult = await packagesApi.installToProject(projectId, result.package.dirName);
        setCurrentProjectPackages(projResult.packages);
      }
      await refreshPackageRegistry();
      // Rebind the canvas node to the new/updated kind so re-opening Settings
      // resolves to the new descriptor (e.g. its readOnly flag), not the
      // source built-in. Match by label — Save-As preserves it. Also re-seed
      // `data.code` / `data.defaultCode` with the body we just persisted, so the
      // editor remount picks them up instead of clobbering them with the old
      // source descriptor's starter (or an empty initial state).
      const matchNorm = normalizeTemplateLabel(nodeLabel);
      const newKind = result.package.templates.find((k) => normalizeTemplateLabel(k.label) === matchNorm);
      if (newKind) {
        const savedBody = runtimeCodeFromRfNode(canvasNode);
        setNodes((nodes) =>
          nodes.map((n) =>
            String(n.id) === nodeId
              ? {
                  ...n,
                  data: {
                    ...n.data,
                    nodeType: newKind.id,
                    code: savedBody,
                    defaultCode: savedBody,
                  },
                }
              : n,
          ),
        );
      }
      showToast(
        replacedExistingKind
          ? `Replaced "${nodeLabel}" in the package.`
          : `Added "${nodeLabel}" as a new kind in the package.`,
        "success",
      );
      onClose();
    } catch (err) {
      showToast((err as Error)?.message ?? "Save As failed.", "error");
    } finally {
      setBusy(false);
      setBusyKind(null);
    }
  }, [buildDraft, busy, canvasNode, nodeId, nodeLabel, onClose, projectId, setNodes, showToast, targetKey]);

  // Export the same draft as a .curio.zip without installing it. Shares the
  // `busy` flag with Save so the two can never run concurrently, and leaves
  // the modal open - an export is not a commit.
  //
  // Deliberately sends the *same* envelope Save would: `/factory/build` reads
  // only manifest/sources/readme/license and ignores `replace`. Both endpoints
  // run preserve_unedited_sources, so the downloaded zip carries the same
  // template bodies Save would have installed - including the real source of
  // siblings this draft only has placeholders for. Not literally byte-identical:
  // each request stamps its own `createdAt` when the draft omits one.
  const onExport = useCallback(async () => {
    if (!canvasNode || busy) return;
    setBusy(true);
    setBusyKind("export");
    try {
      const built = await buildDraft();
      if (!built) return;
      const { blob, filename } = await packagesApi.factoryBuild(
        buildFactoryInstallEnvelope(built.draft, built.replace),
      );
      triggerBlobDownload(blob, filename);
      showToast(`Exported ${filename}.`, "success");
    } catch (err) {
      showToast((err as Error)?.message ?? "Export failed.", "error");
    } finally {
      setBusy(false);
      setBusyKind(null);
    }
  }, [buildDraft, busy, canvasNode, showToast]);

  if (!show) return null;

  return (
    <ModalShell preservePackagePaletteOpen onClose={busy ? () => {} : onClose} titleId="save-as-package-title">
      <div className={styles.content}>
        <h2 id="save-as-package-title" className={styles.title}>Save as package node</h2>
        <p className={styles.subtitle}>
          Save <strong>{nodeLabel}</strong> into an installed package or create a new one.
        </p>

        <label className={styles.fieldLabel} htmlFor="save-as-package-target">
          Destination package
        </label>
        <div className={styles.selectWrap}>
          <select
            id="save-as-package-target"
            className={styles.select}
            value={targetKey}
            disabled={busy}
            onChange={(e) => setTargetKey(e.target.value)}
          >
            <option value={SAVE_AS_NEW_PACK}>New package…</option>
            {packageOptions.map((opt) => (
              <option key={opt.sectionKey} value={opt.sectionKey}>
                {opt.displayName}
              </option>
            ))}
          </select>
          <span className={styles.selectChevron} aria-hidden>
            ▼
          </span>
        </div>

        {targetKey === SAVE_AS_NEW_PACK ? (
          <div className={styles.newPackageField}>
            <label className={styles.fieldLabel} htmlFor="save-as-new-package-name">
              New package name
            </label>
            <input
              id="save-as-new-package-name"
              className={styles.input}
              value={newPackageName}
              disabled={busy}
              onChange={(e) => setNewPackageName(e.target.value)}
              placeholder="My analytics package"
            />
          </div>
        ) : willReplace ? (
          <p className={styles.warning} role="alert">
            <strong>Replace existing node.</strong> &quot;{nodeLabel}&quot; already exists in{" "}
            {targetPackageName ?? "this package"}. Saving will replace that kind&apos;s template and
            settings with this canvas node.
          </p>
        ) : (
          <p className={styles.hint}>Adds this node as a new kind in the selected package.</p>
        )}

        <div className={styles.footer}>
          <button type="button" className={styles.ghostBtn} disabled={busy} onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className={styles.ghostBtn}
            disabled={busy}
            title="Download this node as a .curio.zip package without installing it"
            onClick={() => void onExport()}
          >
            {busyKind === "export" ? "Exporting…" : "Export"}
          </button>
          <button type="button" className={styles.primaryBtn} disabled={busy} onClick={() => void onConfirm()}>
            {busyKind === "save" ? "Saving…" : willReplace ? "Replace" : "Save"}
          </button>
        </div>
      </div>
    </ModalShell>
  );
}


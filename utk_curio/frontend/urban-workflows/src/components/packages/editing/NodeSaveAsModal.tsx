import React, { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { useReactFlow } from "reactflow";
import ModalShell from "../../ModalShell";
import { packagesApi, refreshPackageRegistry } from "../../../api/packagesApi";
import { getPaletteNodeTypes, subscribeToRegistry } from "../../../registry";
import { groupPalettePackages } from "../../menus/nodes/toolsMenuPackagePalette/model";
import { useStarterContext } from "../../../providers/StarterProvider";
import { useToastContext } from "../../../providers/ToastProvider";
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
  const { getNodes, setNodes } = useReactFlow();
  const { getStarters } = useStarterContext();
  const { showToast } = useToastContext();
  const [targetKey, setTargetKey] = useState<string>(SAVE_AS_NEW_PACK);
  const [newPackageName, setNewPackageName] = useState("");
  const [busy, setBusy] = useState(false);

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

  const canvasNode = useMemo(() => {
    if (!show) return null;
    return getNodes().find((n) => String(n.id) === nodeId) ?? null;
  }, [show, nodeId, getNodes]);

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

  const onConfirm = useCallback(async () => {
    if (!canvasNode || busy) return;
    setBusy(true);
    try {
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
          return;
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
        return;
      }

      const result = await packagesApi.factoryInstall(buildFactoryInstallEnvelope(draft, replace));
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
    }
  }, [busy, canvasNode, getStarters, newPackageName, nodeId, nodeLabel, onClose, setNodes, showToast, targetKey]);

  if (!show) return null;

  return (
    <ModalShell preservePackagePaletteOpen onClose={busy ? () => {} : onClose}>
      <div className={styles.content}>
        <h2 className={styles.title}>Save As pkg node</h2>
        <p className={styles.subtitle}>
          Save <strong>{nodeLabel}</strong> into an installed pkg or create a new one.
        </p>

        <label className={styles.fieldLabel} htmlFor="save-as-package-target">
          Destination pkg
        </label>
        <div className={styles.selectWrap}>
          <select
            id="save-as-package-target"
            className={styles.select}
            value={targetKey}
            disabled={busy}
            onChange={(e) => setTargetKey(e.target.value)}
          >
            <option value={SAVE_AS_NEW_PACK}>New pkg…</option>
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
              New pkg name
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
          <p className={styles.hint}>Adds this node as a new kind in the selected pkg.</p>
        )}

        <div className={styles.footer}>
          <button type="button" className={styles.ghostBtn} disabled={busy} onClick={onClose}>
            Cancel
          </button>
          <button type="button" className={styles.primaryBtn} disabled={busy} onClick={() => void onConfirm()}>
            {busy ? "Saving…" : willReplace ? "Replace" : "Save"}
          </button>
        </div>
      </div>
    </ModalShell>
  );
}


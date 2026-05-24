import React, { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { useReactFlow } from "reactflow";
import ModalShell from "../../ModalShell";
import { packsApi, refreshPackRegistry } from "../../../api/packsApi";
import { getPaletteNodeTypes, subscribeToRegistry } from "../../../registry";
import { groupPalettePacks } from "../../menus/nodes/toolsMenuPackPalette/model";
import { useTemplateContext } from "../../../providers/TemplateProvider";
import { useToastContext } from "../../../providers/ToastProvider";
import {
  SAVE_AS_NEW_PACK,
  buildFactoryInstallEnvelope,
  buildSaveAsInstallDraft,
  canvasKindLabelFromNode,
  normalizeKindLabel,
  runtimeCodeFromRfNode,
  saveAsWouldReplaceByLabel,
} from "../../../utils/palettePackFactoryDraft";
import { getFlowNodeCanonicalType } from "../../../utils/flowNodeCanonicalType";
import { filterForkParentHiddenPalettePackGroups } from "../../../utils/forkPackLineage";
import { tryGetNodeDescriptor } from "../../../registry/nodeRegistry";
import { NodeKindId } from "../../../registry/types";
import styles from "./NodeSaveAsModal.module.css";

const NOOP = () => () => {};

function registryBootstrapKey(): string {
  return String(getPaletteNodeTypes().length);
}

function packLabelsForSectionKey(sectionKey: string): string[] {
  return getPaletteNodeTypes()
    .filter(
      (d) =>
        d.source === "pack" &&
        d.pack &&
        `${d.pack.packId}@${d.pack.major}` === sectionKey,
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
  const { getTemplates } = useTemplateContext();
  const { showToast } = useToastContext();
  const [targetKey, setTargetKey] = useState<string>(SAVE_AS_NEW_PACK);
  const [newPackName, setNewPackName] = useState("");
  const [busy, setBusy] = useState(false);

  const registryKey = useSyncExternalStore(
    typeof window !== "undefined" ? subscribeToRegistry : NOOP,
    registryBootstrapKey,
    () => "ssr",
  );
  void registryKey;

  const packOptions = useMemo(() => {
    const packTypes = getPaletteNodeTypes().filter((d) => d.source === "pack");
    return filterForkParentHiddenPalettePackGroups(groupPalettePacks(packTypes))
      .filter((g) => g.descriptors[0]?.pack?.readOnly !== true)
      .map((g) => ({
        sectionKey: g.key,
        displayName: g.descriptors[0]?.pack?.name?.trim() || g.label,
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
    const desc = tryGetNodeDescriptor(nt as NodeKindId);
    if (!desc) return "Node";
    return canvasKindLabelFromNode(canvasNode, desc);
  }, [canvasNode]);

  useEffect(() => {
    if (!show) return;
    setTargetKey(packOptions[0]?.sectionKey ?? SAVE_AS_NEW_PACK);
    setNewPackName(`${nodeLabel} pack`);
  }, [show, nodeLabel, packOptions]);

  const willReplace = useMemo(() => {
    if (targetKey === SAVE_AS_NEW_PACK) return false;
    const labels = packLabelsForSectionKey(targetKey);
    const norm = normalizeKindLabel(nodeLabel);
    return labels.some((l) => normalizeKindLabel(l) === norm);
  }, [targetKey, nodeLabel, registryKey]);

  const targetPackName = useMemo(
    () => packOptions.find((p) => p.sectionKey === targetKey)?.displayName,
    [packOptions, targetKey],
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
          target: { kind: "new", packDisplayName: newPackName.trim() || undefined },
          getTemplates,
        });
      } else {
        const { packs } = await packsApi.listInstalled();
        const pack = packs.find((p) => `${p.packId}@${p.major}` === targetKey);
        if (!pack) {
          showToast("Could not load the selected pack.", "warning");
          return;
        }
        replacedExistingKind = saveAsWouldReplaceByLabel(pack, nodeLabel);
        draft = buildSaveAsInstallDraft({
          canvasNode,
          target: { kind: "installed", pack },
          getTemplates,
        });
        replace = true;
      }

      if (!draft) {
        showToast("Could not build a pack draft from this node.", "error");
        return;
      }

      const result = await packsApi.factoryInstall(buildFactoryInstallEnvelope(draft, replace));
      await refreshPackRegistry();
      // Rebind the canvas node to the new/updated kind so re-opening Settings
      // resolves to the new descriptor (e.g. its readOnly flag), not the
      // source built-in. Match by label — Save-As preserves it. Also re-seed
      // `data.code` / `data.defaultCode` with the body we just persisted, so the
      // editor remount picks them up instead of clobbering them with the old
      // source descriptor's starter (or an empty initial state).
      const matchNorm = normalizeKindLabel(nodeLabel);
      const newKind = result.pack.kinds.find((k) => normalizeKindLabel(k.label) === matchNorm);
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
          ? `Replaced "${nodeLabel}" in the pack.`
          : `Added "${nodeLabel}" as a new kind in the pack.`,
        "success",
      );
      onClose();
    } catch (err) {
      showToast((err as Error)?.message ?? "Save As failed.", "error");
    } finally {
      setBusy(false);
    }
  }, [busy, canvasNode, getTemplates, newPackName, nodeId, nodeLabel, onClose, setNodes, showToast, targetKey]);

  if (!show) return null;

  return (
    <ModalShell preservePackPaletteOpen onClose={busy ? () => {} : onClose}>
      <div className={styles.content}>
        <h2 className={styles.title}>Save As pack node</h2>
        <p className={styles.subtitle}>
          Save <strong>{nodeLabel}</strong> into an installed pack or create a new one.
        </p>

        <label className={styles.fieldLabel} htmlFor="save-as-pack-target">
          Destination pack
        </label>
        <div className={styles.selectWrap}>
          <select
            id="save-as-pack-target"
            className={styles.select}
            value={targetKey}
            disabled={busy}
            onChange={(e) => setTargetKey(e.target.value)}
          >
            <option value={SAVE_AS_NEW_PACK}>New pack…</option>
            {packOptions.map((opt) => (
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
          <div className={styles.newPackField}>
            <label className={styles.fieldLabel} htmlFor="save-as-new-pack-name">
              New pack name
            </label>
            <input
              id="save-as-new-pack-name"
              className={styles.input}
              value={newPackName}
              disabled={busy}
              onChange={(e) => setNewPackName(e.target.value)}
              placeholder="My analytics pack"
            />
          </div>
        ) : willReplace ? (
          <p className={styles.warning} role="alert">
            <strong>Replace existing node.</strong> &quot;{nodeLabel}&quot; already exists in{" "}
            {targetPackName ?? "this pack"}. Saving will replace that kind&apos;s template and
            settings with this canvas node.
          </p>
        ) : (
          <p className={styles.hint}>Adds this node as a new kind in the selected pack.</p>
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


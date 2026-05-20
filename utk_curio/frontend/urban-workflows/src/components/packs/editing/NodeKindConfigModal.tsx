import React, { useCallback, useEffect, useMemo, useState } from "react";
import ModalShell from "../../ModalShell";
import type { Category, Editor, Engine } from "../../../pages/nodes/factoryDraftModel";
import type { CanvasKindConfig } from "../../../utils/canvasKindConfig";
import { canvasKindConfigFromDescriptor } from "../../../utils/canvasKindConfig";
import { tryGetNodeDescriptor } from "../../../registry/nodeRegistry";
import { NodeKindId } from "../../../registry/types";
import { KindPortEditor } from "./KindPortEditor";
import styles from "./NodeKindConfigModal.module.css";

export function NodeKindConfigModal({
  show,
  nodeId,
  nodeType,
  storedConfig,
  storedLabel,
  templateCode,
  onClose,
  onSave,
}: {
  show: boolean;
  nodeId: string;
  nodeType: NodeKindId;
  storedConfig: Partial<CanvasKindConfig> | null;
  storedLabel?: string;
  /** Runtime editor body used to seed stored template fields (not edited in this modal). */
  templateCode: string;
  onClose: () => void;
  onSave: (config: CanvasKindConfig) => void;
}) {
  const desc = useMemo(() => tryGetNodeDescriptor(nodeType), [nodeType]);
  const [config, setConfig] = useState<CanvasKindConfig | null>(null);

  useEffect(() => {
    if (!show || !desc) return;
    const nodeData = {
      packKindConfig: storedConfig ?? undefined,
      packKindLabel: storedLabel,
    };
    setConfig(
      canvasKindConfigFromDescriptor(
        desc,
        { id: nodeId, data: nodeData } as { id: string; data: object },
        templateCode,
      ),
    );
  }, [show, desc, nodeId, storedConfig, storedLabel, templateCode]);

  const patch = useCallback((p: Partial<CanvasKindConfig>) => {
    setConfig((prev) => (prev ? { ...prev, ...p } : prev));
  }, []);

  const onEditorChange = useCallback((editor: Editor) => {
    setConfig((prev) => {
      if (!prev) return prev;
      const next = { ...prev, editor };
      if (editor === "code") {
        next.hasCode = true;
        next.hasGrammar = false;
        next.engine = "python";
      } else if (editor === "grammar") {
        next.hasCode = false;
        next.hasGrammar = true;
        next.hasWidgets = false;
        next.engine = "javascript";
      } else if (editor === "widgets") {
        next.hasCode = true;
        next.hasWidgets = true;
        next.hasGrammar = false;
      } else {
        next.hasCode = false;
        next.hasWidgets = false;
        next.hasGrammar = false;
      }
      if (!next.hasCode && !next.hasGrammar) next.hasExplanation = false;
      return next;
    });
  }, []);

  if (!show || !desc || !config) return null;

  return (
    <ModalShell onClose={onClose} size="large" layer="overlay">
      <div className={styles.content}>
        <h2 className={styles.title}>Node configuration</h2>
        <p className={styles.subtitle}>
          Edit kind metadata, ports, and editor tabs for this canvas node. Changes apply when you
          Save As or Save draft in the packs palette.
        </p>

        <p className={styles.sectionTitle}>Identity</p>
        <div className={styles.field}>
          <label className={styles.fieldLabel} htmlFor="kind-config-label">
            Node title
          </label>
          <input
            id="kind-config-label"
            className={styles.input}
            value={config.label}
            onChange={(e) => patch({ label: e.target.value })}
          />
        </div>

        <div className={styles.field}>
          <label className={styles.fieldLabel} htmlFor="kind-config-description">
            Description
          </label>
          <textarea
            id="kind-config-description"
            className={styles.textarea}
            style={{ minHeight: 72 }}
            value={config.description}
            onChange={(e) => patch({ description: e.target.value })}
          />
        </div>

        <p className={styles.sectionTitle}>Editor</p>
        <div className={styles.row}>
          <div className={styles.field}>
            <label className={styles.fieldLabel} htmlFor="kind-config-editor">
              Editor mode
            </label>
            <select
              id="kind-config-editor"
              className={styles.select}
              value={config.editor}
              onChange={(e) => onEditorChange(e.target.value as Editor)}
            >
              <option value="code">code</option>
              <option value="widgets">widgets</option>
              <option value="grammar">grammar</option>
              <option value="none">none</option>
            </select>
          </div>

          <div className={styles.field}>
            <label className={styles.fieldLabel} htmlFor="kind-config-engine">
              Engine
            </label>
            <select
              id="kind-config-engine"
              className={styles.select}
              value={config.engine}
              onChange={(e) => patch({ engine: e.target.value as Engine })}
            >
              <option value="python">python</option>
              <option value="javascript">javascript</option>
            </select>
          </div>
        </div>

        <div className={styles.checkGrid}>
          <label className={styles.checkRow}>
            <input
              type="checkbox"
              checked={config.hasCode}
              onChange={(e) => patch({ hasCode: e.target.checked })}
            />
            hasCode
          </label>
          <label className={styles.checkRow}>
            <input
              type="checkbox"
              checked={config.hasWidgets}
              onChange={(e) => patch({ hasWidgets: e.target.checked })}
            />
            hasWidgets
          </label>
          <label className={styles.checkRow}>
            <input
              type="checkbox"
              checked={config.hasGrammar}
              onChange={(e) => patch({ hasGrammar: e.target.checked })}
            />
            hasGrammar
          </label>
        </div>

        <p className={styles.sectionTitle}>Editor tabs</p>
        <div className={styles.checkGrid}>
          <label className={styles.checkRow}>
            <input
              type="checkbox"
              checked={config.hasProvenance}
              onChange={(e) => patch({ hasProvenance: e.target.checked })}
            />
            Provenance tab
          </label>
          <label className={styles.checkRow}>
            <input
              type="checkbox"
              checked={config.hasExplanation}
              disabled={!config.hasCode && !config.hasGrammar}
              onChange={(e) => patch({ hasExplanation: e.target.checked })}
            />
            Explanation tab
          </label>
        </div>

        <p className={styles.sectionTitle}>Ports</p>
        <KindPortEditor
          title="Input ports"
          ports={config.inputPorts}
          onChange={(inputPorts) => patch({ inputPorts })}
        />
        <KindPortEditor
          title="Output ports"
          ports={config.outputPorts}
          onChange={(outputPorts) => patch({ outputPorts })}
        />

        <div className={styles.footer}>
          <button type="button" className={styles.ghostBtn} onClick={onClose}>
            Cancel
          </button>
          <button type="button" className={styles.primaryBtn} onClick={() => onSave(config)}>
            Save configuration
          </button>
        </div>
      </div>
    </ModalShell>
  );
}


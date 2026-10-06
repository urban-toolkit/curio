import React, { useCallback, useEffect, useMemo, useState } from "react";
import ModalShell from "../../ModalShell";
import {
  packagesApi,
  dependencyFailureNotice,
  withRestartNotice,
  type FunctionPackagePayload,
  type FunctionParameterBinding,
  type FunctionParameterPayload,
  type FunctionParameterUse,
  type FunctionPayload,
} from "../../../services/packages";
import { useStarterContext } from "../../../providers/StarterProvider";
import { useToastContext } from "../../../providers/ToastProvider";
import { useFlowContext } from "../../../providers/FlowProvider";
import { installDraftToProject } from "../../../providers/packages/installDraftToProject";
import {
  SAVE_AS_NEW_PACK,
  buildFactoryInstallEnvelope,
  buildFunctionInstallDraft,
  type TemplateSaveTarget,
} from "../../../utils/palettePackageFactoryDraft";
import { WIDGET_KIND_LABELS, type WidgetDef } from "../../../utils/widgets/widgetModel";
import { WidgetForm } from "../../editing/widgets/WidgetForm";
import { WidgetTag } from "../../editing/widgets/WidgetTag";
import { PackageTargetPicker, useWritablePackageOptions } from "./PackageTargetPicker";
import styles from "./NodeSaveAsModal.module.css";
import own from "./NodeFromFunctionModal.module.css";

/** One function, as the picker names it. */
interface FunctionChoice {
  key: string;
  pkg: FunctionPackagePayload;
  module: string;
  fn: FunctionPayload;
}

/** What one parameter is given, with the widget and value kept while the user switches. */
interface ParameterState {
  use: FunctionParameterUse;
  widget: WidgetDef;
  value: string;
}

const USE_LABELS: Record<FunctionParameterUse, string> = {
  widget: "A widget",
  fixed: "A fixed value",
  input: "An input",
  default: "Its default",
};

/** `max_height` reads `Max height`, as the backend labels a widget. */
export function functionLabel(name: string): string {
  const text = name.replace(/^_+|_+$/g, "").replace(/_/g, " ").trim() || name;
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function initialState(param: FunctionParameterPayload): ParameterState {
  return {
    use: param.use,
    widget: param.widget ?? { name: param.name, type: "text", label: functionLabel(param.name), default: "" },
    value: param.defaultText ?? "",
  };
}

function signatureText(fn: FunctionPayload): string {
  return `${fn.name}(${fn.parameters.map((p) => p.name).join(", ")})`;
}

function valueText(value: unknown): string {
  return typeof value === "string" ? value : JSON.stringify(value);
}

/**
 * New node from a Python function (SCOUT's Compute Catalog, the Curio way).
 *
 * Pick a function in a module an installed package ships; give each parameter
 * a widget, a fixed value, an input or its default; Curio writes a template
 * whose code imports the function and calls it with those references, and
 * adds it to a package the way Save as package node does: the same
 * destination picker, the same draft builder, the same install.
 */
export function NodeFromFunctionModal({
  show,
  onClose,
  onSaved,
}: {
  show: boolean;
  onClose: () => void;
  /** Called with the package the template was added to. */
  onSaved?: (dirName: string) => void;
}) {
  const { getStarters } = useStarterContext();
  const { showToast } = useToastContext();
  const { ensureProjectId } = useFlowContext();
  const { options: packageOptions } = useWritablePackageOptions();

  const [packages, setPackages] = useState<FunctionPackagePayload[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [choiceKey, setChoiceKey] = useState("");
  const [label, setLabel] = useState("");
  const [params, setParams] = useState<Record<string, ParameterState>>({});
  const [editing, setEditing] = useState<string | null>(null);
  const [targetKey, setTargetKey] = useState<string>(SAVE_AS_NEW_PACK);
  const [newPackageName, setNewPackageName] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    if (!show) return;
    let live = true;
    setPackages(null);
    setLoadError(null);
    setChoiceKey("");
    setProblem(null);
    packagesApi
      .listFunctions()
      .then((res) => live && setPackages(res.packages))
      .catch((err) => live && setLoadError((err as Error)?.message ?? "Could not list the functions."));
    return () => {
      live = false;
    };
  }, [show]);

  const choices = useMemo(() => {
    const out = new Map<string, FunctionChoice>();
    for (const pkg of packages ?? []) {
      for (const mod of pkg.modules) {
        for (const fn of mod.functions) {
          const key = `${pkg.dirName}|${mod.module}|${fn.name}`;
          out.set(key, { key, pkg, module: mod.module, fn });
        }
      }
    }
    return out;
  }, [packages]);

  const choice = choices.get(choiceKey) ?? null;

  const pick = useCallback(
    (key: string) => {
      setChoiceKey(key);
      setEditing(null);
      setProblem(null);
      const next = choices.get(key);
      if (!next) return;
      const nodeLabel = functionLabel(next.fn.name);
      setLabel(nodeLabel);
      setNewPackageName(`${nodeLabel} package`);
      setParams(Object.fromEntries(next.fn.parameters.map((p) => [p.name, initialState(p)])));
      // The function's own package when it can take the template; a new one otherwise.
      const ownKey = packageOptions.find((o) => o.sectionKey === next.pkg.dirName)?.sectionKey;
      setTargetKey(ownKey ?? SAVE_AS_NEW_PACK);
    },
    [choices, packageOptions],
  );

  const setParam = (name: string, patch: Partial<ParameterState>) =>
    setParams((prev) => ({ ...prev, [name]: { ...prev[name]!, ...patch } }));

  const widgetsBut = (name: string): WidgetDef[] =>
    Object.entries(params)
      .filter(([other, state]) => other !== name && state.use === "widget")
      .map(([, state]) => state.widget);

  const inputSlot = (name: string): number => {
    let slot = 0;
    for (const p of choice?.fn.parameters ?? []) {
      if (p.name === name) return slot;
      if (params[p.name]?.use === "input") slot += 1;
    }
    return slot;
  };

  const onCreate = useCallback(async () => {
    if (!choice || busy) return;
    setBusy(true);
    setProblem(null);
    try {
      const bindings: Record<string, FunctionParameterBinding> = {};
      for (const p of choice.fn.parameters) {
        const state = params[p.name]!;
        bindings[p.name] =
          state.use === "widget" ? { use: "widget", widget: state.widget }
          : state.use === "fixed" ? { use: "fixed", value: state.value }
          : { use: state.use };
      }
      const written = await packagesApi.functionTemplate({
        dirName: choice.pkg.dirName,
        module: choice.module,
        function: choice.fn.name,
        label: label.trim() || undefined,
        bindings,
      });
      let target: TemplateSaveTarget;
      let replace = false;
      if (targetKey === SAVE_AS_NEW_PACK) {
        target = { kind: "new", packageDisplayName: newPackageName.trim() || undefined };
      } else {
        const { packages: installed } = await packagesApi.listInstalled();
        const pkg = installed.find((p) => `${p.packageId}@${p.major}` === targetKey);
        if (!pkg) {
          setProblem("Could not load the selected package.");
          return;
        }
        target = { kind: "installed", package: pkg };
        replace = true;
      }
      const draft = buildFunctionInstallDraft({ written, target, getStarters });
      const result = await installDraftToProject(buildFactoryInstallEnvelope(draft, replace), ensureProjectId);
      const nodeLabel = written.template.label;
      const depNotice = dependencyFailureNotice(`Saved ${nodeLabel}`, result);
      showToast(
        withRestartNotice(
          depNotice ?? `Added "${nodeLabel}" to ${result.package.name}. Drag it from the Node Catalog in the Tools panel.`,
          result.restartRecommended,
        ),
        depNotice ? "error" : "success",
      );
      onSaved?.(result.package.dirName);
      onClose();
    } catch (err) {
      setProblem((err as Error)?.message ?? "Could not create the node.");
    } finally {
      setBusy(false);
    }
  }, [busy, choice, ensureProjectId, getStarters, label, newPackageName, onClose, onSaved, params, showToast, targetKey]);

  if (!show) return null;

  const noFunctions = packages !== null && choices.size === 0;

  return (
    <ModalShell
      preservePackagePaletteOpen
      size="large"
      layer="overlay"
      onClose={busy ? () => {} : onClose}
      titleId="node-from-function-title"
    >
      <div className={`${styles.content} ${own.dialog}`} data-node-from-function="true">
        <h2 id="node-from-function-title" className={styles.title}>New node from a Python function</h2>
        <p className={styles.subtitle}>
          Pick a function in a module of an installed package. Each parameter becomes a widget, a fixed
          value or an input, and the node&apos;s code calls the function with them.
        </p>

        <div className={own.body} data-node-from-function-body="true">
          <label className={styles.fieldLabel} htmlFor="node-from-function-choice">
            Function
          </label>
          <div className={styles.selectWrap}>
            <select
              id="node-from-function-choice"
              className={styles.select}
              value={choiceKey}
              disabled={busy || packages === null || noFunctions}
              onChange={(e) => pick(e.target.value)}
            >
              <option value="">
                {packages === null ? (loadError ? "Could not list the functions" : "Reading the modules…") : "Choose a function"}
              </option>
              {(packages ?? []).map((pkg) => (
                <optgroup key={pkg.dirName} label={pkg.name}>
                  {pkg.modules.flatMap((mod) =>
                    mod.problem
                      ? [
                          <option key={mod.module} value="" disabled>
                            {mod.module}: {mod.problem}
                          </option>,
                        ]
                      : mod.functions.map((fn) => (
                          <option
                            key={`${mod.module}.${fn.name}`}
                            value={`${pkg.dirName}|${mod.module}|${fn.name}`}
                            disabled={!!fn.problem}
                            title={fn.problem ?? fn.doc}
                          >
                            {mod.module}.{signatureText(fn)}
                          </option>
                        )),
                  )}
                </optgroup>
              ))}
            </select>
            <span className={styles.selectChevron} aria-hidden>
              ▼
            </span>
          </div>
          {loadError ? <p className={styles.warning} role="alert">{loadError}</p> : null}
          {noFunctions ? (
            <p className={styles.hint}>
              No installed package ships a Python module. A module is a <code>.py</code> file, or a folder of them,
              in a package&apos;s <code>sources/</code> folder.
            </p>
          ) : null}
          {choice?.fn.problem ? <p className={styles.warning} role="alert">{choice.fn.problem}</p> : null}

          {choice ? (
            <>
              {choice.fn.doc ? <p className={styles.hint}>{choice.fn.doc}</p> : null}
              <div className={styles.fieldLabel}>Parameters</div>
              {choice.fn.parameters.length === 0 ? (
                <p className={styles.hint}>{choice.fn.name} takes no parameters.</p>
              ) : (
                <ul className={own.parameters}>
                  {choice.fn.parameters.map((p) => {
                    const state = params[p.name];
                    if (!state) return null;
                    return (
                      <li key={p.name} className={own.parameter} data-function-parameter={p.name}>
                        <div className={own.parameterHead}>
                          <span className={own.parameterName}>{p.name}</span>
                          <span className={own.parameterHint}>
                            {p.annotation ? `: ${p.annotation}` : ""}
                            {p.hasDefault ? ` = ${p.defaultText}` : ""}
                          </span>
                          <select
                            className={own.useSelect}
                            aria-label={`What ${p.name} is given`}
                            value={state.use}
                            disabled={busy}
                            onChange={(e) => {
                              setEditing(null);
                              setParam(p.name, { use: e.target.value as FunctionParameterUse });
                            }}
                          >
                            {(["widget", "fixed", "input", "default"] as const)
                              .filter((use) => use !== "default" || p.hasDefault)
                              .map((use) => (
                                <option key={use} value={use}>
                                  {use === "default" ? `${USE_LABELS[use]} (${p.defaultText})` : USE_LABELS[use]}
                                </option>
                              ))}
                          </select>
                        </div>
                        {state.use === "widget" ? (
                          <div className={own.parameterBody}>
                            <WidgetTag name={p.name} disabled />
                            <span className={own.parameterHint}>
                              {WIDGET_KIND_LABELS[state.widget.type]}, starting at {valueText(state.widget.default)}
                            </span>
                            {editing !== p.name ? (
                              <button
                                type="button"
                                className={styles.ghostBtn}
                                disabled={busy}
                                onClick={() => setEditing(p.name)}
                              >
                                Edit widget
                              </button>
                            ) : null}
                          </div>
                        ) : null}
                        {state.use === "widget" && editing === p.name ? (
                          <WidgetForm
                            initial={state.widget}
                            others={widgetsBut(p.name)}
                            onSave={(widget) => {
                              setParam(p.name, { widget });
                              setEditing(null);
                            }}
                            onCancel={() => setEditing(null)}
                          />
                        ) : null}
                        {state.use === "fixed" ? (
                          <input
                            className={styles.input}
                            aria-label={`Value of ${p.name}`}
                            value={state.value}
                            disabled={busy}
                            placeholder="2, 'winter', [1, 2]"
                            onChange={(e) => setParam(p.name, { value: e.target.value })}
                          />
                        ) : null}
                        {state.use === "input" ? (
                          <p className={own.parameterHint}>The node&apos;s input {inputSlot(p.name)}.</p>
                        ) : null}
                      </li>
                    );
                  })}
                </ul>
              )}

              <label className={styles.fieldLabel} htmlFor="node-from-function-label">
                Node name
              </label>
              <input
                id="node-from-function-label"
                className={`${styles.input} ${own.labelInput}`}
                value={label}
                disabled={busy}
                onChange={(e) => setLabel(e.target.value)}
              />

              <PackageTargetPicker
                idPrefix="node-from-function"
                options={packageOptions}
                targetKey={targetKey}
                onTargetKey={setTargetKey}
                newPackageName={newPackageName}
                onNewPackageName={setNewPackageName}
                busy={busy}
              >
                <p className={styles.hint}>Adds this node as a new kind in the selected package.</p>
              </PackageTargetPicker>
            </>
          ) : null}
        </div>

        {problem ? (
          <p className={styles.warning} role="alert">
            {problem}
          </p>
        ) : null}

        <div className={styles.footer}>
          <button type="button" className={styles.ghostBtn} disabled={busy} onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className={styles.primaryBtn}
            disabled={busy || !choice || !!choice.fn.problem || editing !== null}
            onClick={() => void onCreate()}
          >
            {busy ? "Creating…" : "Create node"}
          </button>
        </div>
      </div>
    </ModalShell>
  );
}

export default NodeFromFunctionModal;

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  packagesApi,
  refreshPackageRegistry,
  type FactoryCapabilities,
  type InstallResponse,
} from "../../api/packagesApi";
import { SupportedType } from "../../constants";
import modalStyles from "./NodeFactoryModal.module.css";
import styles from "./NodeFactory.module.css";
import {
  Category,
  Draft,
  Editor,
  Engine,
  KindDraft,
  PortDraft,
  factoryUiMakeId,
  makeDraft,
  makeKind,
  toApiPayload,
} from "./factoryDraftModel";
import { lineageCoordKey } from "../../utils/forkPackageLineage";

/**
 * Node Factory wizard — five-step authoring flow.
 *
 * The wizard maintains a single draft state object whose shape matches
 * the request body of ``POST /api/packages/factory/build`` and
 * ``POST /api/packages/factory/install``. Step 5 calls the backend to
 * validate, then either downloads the archive ("Export") or installs
 * it into the user's package store ("Save and install").
 *
 * Validation is intentionally deferred to the backend: the manifest
 * schema lives in ``utk_curio/backend/app/packages/manifest.py`` and
 * ``docs/schemas/node-package.v3.json``. Re-implementing it client-side
 * would put us on the path to drift. Local validation here is limited
 * to "is the form fully filled in" checks so the "Next" buttons can
 * guide the user; semantic errors come back from the API and are
 * rendered in the Step 5 error box.
 *
 * User-facing overview: ``docs/WAREHOUSE.md``.
 */

const SUPPORTED_TYPE_OPTIONS = Object.values(SupportedType);
const CARDINALITY_OPTIONS = ["1", "n", "[0,1]", "[1,n]", "[1,2]", "2"];
const KNOWN_PERMISSIONS = [
  "filesystem.read",
  "filesystem.write",
  "network.fetch",
  "sandbox.python",
  "sandbox.javascript",
];

const STEPS = [
  { id: 1, title: "Metadata" },
  { id: 2, title: "Kinds and ports" },
  { id: 3, title: "Source" },
  { id: 4, title: "Dependencies and permissions" },
  { id: 5, title: "Validate and publish" },
] as const;

// Mirror of backend's _SOURCE_FILENAME_RE in utk_curio/backend/app/packages/factory.py
// so the wizard surfaces invalid filenames as the user types instead of waiting
// for the validate-and-publish round-trip.
const SOURCE_FILENAME_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,254}\.[A-Za-z0-9]+$/;

function mergeInitialDraft(initial: Draft | null | undefined): Draft {
  if (!initial?.kinds?.length) return makeDraft();
  return {
    ...makeDraft(),
    ...initial,
    kinds: initial.kinds,
  };
}

function draftFingerprint(d: Draft): string {
  try {
    const p = toApiPayload(d);
    return JSON.stringify({
      lineage: d.lineage,
      name: d.name,
      manifest: p.manifest,
      sourcesKeys: Object.keys(p.sources).sort(),
    });
  } catch {
    return String(Date.now());
  }
}

export type NodeFactoryWizardProps = {
  /** New session whenever the modal opens with new data. */
  resetKey: number;
  /** Initial draft for this session (cloned on resetKey change). */
  initialDraft?: Draft | null;
  forkInstallNotice?: boolean;
  onRequestClose?: () => void;
  onInstallSuccess?: (result: InstallResponse) => void;
  onDirtyChange?: (dirty: boolean) => void;
};

export const NodeFactoryWizard: React.FC<NodeFactoryWizardProps> = ({
  resetKey,
  initialDraft,
  forkInstallNotice,
  onRequestClose,
  onInstallSuccess,
  onDirtyChange,
}) => {
  const [draft, setDraft] = useState<Draft>(() => mergeInitialDraft(initialDraft ?? null));
  const [step, setStep] = useState<number>(1);
  const [busy, setBusy] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const [successInfo, setSuccessInfo] = useState<string | null>(null);
  const [fixtureReplace, setFixtureReplace] = useState(false);
  const baselineRef = useRef<string>(draftFingerprint(mergeInitialDraft(initialDraft ?? null)));

  useEffect(() => {
    const merged = mergeInitialDraft(initialDraft ?? null);
    setDraft(merged);
    baselineRef.current = draftFingerprint(merged);
    setStep(1);
    setServerError(null);
    setSuccessInfo(null);
    setFixtureReplace(false);
  }, [resetKey, initialDraft]);

  const isDirty = useMemo(
    () => draftFingerprint(draft) !== baselineRef.current,
    [draft],
  );

  useEffect(() => {
    onDirtyChange?.(isDirty);
  }, [isDirty, onDirtyChange]);

  const updateDraft = useCallback(
    (patch: Partial<Draft>) => setDraft((prev) => ({ ...prev, ...patch })),
    [],
  );

  const updateKind = useCallback(
    (index: number, patch: Partial<KindDraft>) => {
      setDraft((prev) => {
        const kinds = prev.kinds.map((k, i) =>
          i === index ? { ...k, ...patch } : k,
        );
        return { ...prev, kinds };
      });
    },
    [],
  );

  const apiPayload = useMemo(() => toApiPayload(draft), [draft]);

  const stepValid = useMemo(() => {
    switch (step) {
      case 1:
        return (
          /^[a-z][a-z0-9-]*(\.[a-z][a-z0-9-]*)+$/.test(draft.packageId) &&
          draft.name.trim().length > 0 &&
          draft.version.trim().length > 0 &&
          draft.major >= 0
        );
      case 2:
        return draft.kinds.every(
          (k) =>
            k.id.trim().length > 0 &&
            (k.outputPorts.length > 0 || k.inputPorts.length > 0),
        );
      case 3:
        return draft.kinds.every(
          (k) =>
            k.sourceCode.trim().length > 0 &&
            SOURCE_FILENAME_RE.test(k.sourceFilename),
        );
      case 4:
        return true;
      default:
        return true;
    }
  }, [step, draft]);

  const onBuildOrInstall = useCallback(
    async (mode: "build" | "install") => {
      setServerError(null);
      setSuccessInfo(null);
      setBusy(true);
      try {
        const payload = toApiPayload(draft);
        if (mode === "install") {
          const result = await packagesApi.factoryInstall(payload);
          await refreshPackageRegistry();
          onInstallSuccess?.(result);
        } else {
          const { blob, filename } = await packagesApi.factoryBuild(payload);
          const url = URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = url;
          a.download = filename;
          a.click();
          URL.revokeObjectURL(url);
          setSuccessInfo(`Archive ${filename} downloaded.`);
        }
      } catch (err) {
        setServerError((err as Error).message);
      } finally {
        setBusy(false);
      }
    },
    [draft, onInstallSuccess],
  );

  const onPublishToCatalog = useCallback(async () => {
    setServerError(null);
    setSuccessInfo(null);
    setBusy(true);
    try {
      const res = await packagesApi.factoryPublishCatalog({
        ...(toApiPayload(draft) as Record<string, unknown>),
        replace: fixtureReplace,
      });
      setSuccessInfo(
        `Published catalog fixture for ${res.package.dirName}. Written to ${res.catalogDir}. ` +
          "The dev server may reload; commit when ready.",
      );
    } catch (err) {
      setServerError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }, [draft, fixtureReplace]);

  const handleGoHubOrClose = useCallback(() => {
    if (onRequestClose) onRequestClose();
  }, [onRequestClose]);

  const mainColumn = (
    <div className={modalStyles.modalBodyOuter}>
      <div className={`${styles.body} ${modalStyles.bodyOneCol}`}>
        <div>
          {forkInstallNotice ? (
            <p className={modalStyles.forkBanner} role="note">
              <strong>Fork:</strong> “Save and install” adds a <strong>new</strong> package at the coordinate
              you define here. The source package you copied from stays installed unchanged.
            </p>
          ) : null}
          {step === 1 && <Step1Metadata draft={draft} update={updateDraft} />}
          {step === 2 && (
            <Step2Ports draft={draft} update={updateDraft} updateKind={updateKind} />
          )}
          {step === 3 && (
            <Step3Template draft={draft} updateKind={updateKind} />
          )}
          {step === 4 && <Step4Dependencies draft={draft} update={updateDraft} />}
          {step === 5 && (
            <Step5Publish
              draft={draft}
              busy={busy}
              serverError={serverError}
              successInfo={successInfo}
              fixtureReplace={fixtureReplace}
              setFixtureReplace={setFixtureReplace}
              onBuild={() => onBuildOrInstall("build")}
              onInstall={() => onBuildOrInstall("install")}
              onPublishToCatalog={onPublishToCatalog}
              onGoToHub={handleGoHubOrClose}
              forkInstallNotice={!!forkInstallNotice}
            />
          )}

          {step !== STEPS.length ? (
            <div className={styles.footer}>
              <button
                type="button"
                className={styles.ghostButton}
                disabled={step === 1}
                onClick={() => setStep((s) => Math.max(1, s - 1))}
              >
                ← Back
              </button>
              <button
                type="button"
                className={styles.actionButton}
                disabled={!stepValid || step === STEPS.length}
                onClick={() => setStep((s) => Math.min(STEPS.length, s + 1))}
              >
                Next →
              </button>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );

  const stepperEl = (
    <div className={modalStyles.modalStepperRow}>
      <div className={styles.stepper}>
        {STEPS.map((s) => (
          <button
            type="button"
            key={s.id}
            className={
              s.id === step
                ? styles.stepActive
                : s.id < step
                  ? styles.stepDone
                  : styles.step
            }
            onClick={() => setStep(s.id)}
          >
            <span className={styles.stepNumber}>{s.id}</span> {s.title}
          </button>
        ))}
      </div>
      <p style={{ margin: "8px 12px 4px", fontSize: "0.8rem", color: "var(--curio-text-muted)" }}>
        Step {step} of {STEPS.length}
      </p>
    </div>
  );

  return (
    <div className={modalStyles.modalShell}>
      {stepperEl}
      <div className={modalStyles.modalScroll}>{mainColumn}</div>
    </div>
  );
};

/* ─── Step 1: metadata ────────────────────────────────────────────── */

const Step1Metadata: React.FC<{
  draft: Draft;
  update: (patch: Partial<Draft>) => void;
}> = ({ draft, update }) => (
  <div className={styles.panel}>
    <h2 className={styles.panelTitle}>Metadata</h2>
    <p className={styles.panelSubtitle}>
      Identity that downstream users see in the warehouse. The package id is the
      reverse-DNS namespace the wizard uses to derive every canonical kind id
      (<code>&lt;packageId&gt;/&lt;kindId&gt;@&lt;major&gt;</code>).
    </p>
    {draft.lineage ? (
      <p className={styles.lineageCaption}>
        Derived from <code>{lineageCoordKey(draft.lineage.forkedFrom)}</code>
        {" · "}family root <code>{lineageCoordKey(draft.lineage.root)}</code>
      </p>
    ) : null}
    <div className={styles.row}>
      <div className={styles.field}>
        <label className={styles.fieldLabel} htmlFor="packageId">
          Package id (reverse-DNS)
        </label>
        <input
          id="packageId"
          className={styles.input}
          value={draft.packageId}
          placeholder="ai.urbanlab.uhvi"
          onChange={(e) => update({ packageId: e.target.value })}
        />
        <span className={styles.fieldHint}>
          lowercase, dot-separated, two or more segments.
        </span>
      </div>
      <div className={styles.field}>
        <label className={styles.fieldLabel} htmlFor="major">
          Compatibility major
        </label>
        <input
          id="major"
          type="number"
          min={0}
          className={styles.input}
          value={draft.major}
          onChange={(e) => update({ major: Number(e.target.value) })}
        />
        <span className={styles.fieldHint}>
          breaking changes increment this; canonical ids embed it.
        </span>
      </div>
    </div>

    <div className={styles.row}>
      <div className={styles.field}>
        <label className={styles.fieldLabel} htmlFor="name">
          Display name
        </label>
        <input
          id="name"
          className={styles.input}
          value={draft.name}
          placeholder="Urban Heat Vulnerability Index"
          onChange={(e) => update({ name: e.target.value })}
        />
      </div>
      <div className={styles.field}>
        <label className={styles.fieldLabel} htmlFor="publisher">
          Publisher
        </label>
        <input
          id="publisher"
          className={styles.input}
          value={draft.publisher}
          placeholder="Urban Analytics Lab"
          onChange={(e) => update({ publisher: e.target.value })}
        />
      </div>
    </div>

    <div className={styles.row}>
      <div className={styles.field}>
        <label className={styles.fieldLabel} htmlFor="version">
          Version
        </label>
        <input
          id="version"
          className={styles.input}
          value={draft.version}
          onChange={(e) => update({ version: e.target.value })}
        />
        <span className={styles.fieldHint}>semver (e.g. 1.0.0)</span>
      </div>
      <div className={styles.field}>
        <label className={styles.fieldLabel} htmlFor="license">
          License
        </label>
        <input
          id="license"
          className={styles.input}
          value={draft.license}
          onChange={(e) => update({ license: e.target.value })}
        />
      </div>
    </div>

    <div className={styles.field}>
      <label className={styles.fieldLabel} htmlFor="description">
        Description
      </label>
      <textarea
        id="description"
        className={styles.textarea}
        value={draft.description}
        onChange={(e) => update({ description: e.target.value })}
      />
    </div>

    <div className={styles.field}>
      <label className={styles.fieldLabel} htmlFor="curioRuntime">
        Required Curio runtime
      </label>
      <input
        id="curioRuntime"
        className={styles.input}
        value={draft.curioRuntime}
        onChange={(e) => update({ curioRuntime: e.target.value })}
      />
      <span className={styles.fieldHint}>
        e.g. <code>&gt;=0.5.0</code>
      </span>
    </div>
  </div>
);

/* ─── Step 2: ports / kinds ────────────────────────────────────────── */

const Step2Ports: React.FC<{
  draft: Draft;
  update: (patch: Partial<Draft>) => void;
  updateKind: (index: number, patch: Partial<KindDraft>) => void;
}> = ({ draft, update, updateKind }) => {
  const addKind = () => {
    const id = `kind-${draft.kinds.length + 1}`;
    update({ kinds: [...draft.kinds, makeKind(id)] });
  };
  const removeKind = (i: number) => {
    if (draft.kinds.length === 1) return;
    update({ kinds: draft.kinds.filter((_, idx) => idx !== i) });
  };

  return (
    <div className={styles.panel}>
      <h2 className={styles.panelTitle}>Kinds and ports</h2>
      <p className={styles.panelSubtitle}>
        Define each node kind this package ships. Port types use the
        Curio <code>SupportedType</code> enum (DATAFRAME, GEODATAFRAME,
        RASTER, …); the resolver and execution dispatch read both from
        the manifest you assemble here.
      </p>

      <div className={styles.kindList}>
        {draft.kinds.map((kind, i) => (
          <div key={i} className={styles.kindEntry}>
            <div className={styles.kindHeader}>
              <h3 className={styles.kindTitle}>Kind #{i + 1}</h3>
              {draft.kinds.length > 1 && (
                <button className={styles.removeBtn} onClick={() => removeKind(i)}>
                  Remove
                </button>
              )}
            </div>

            <div className={styles.row}>
              <div className={styles.field}>
                <label className={styles.fieldLabel}>Kind id</label>
                <input
                  className={styles.input}
                  value={kind.id}
                  onChange={(e) => {
                    const newId = e.target.value;
                    const extMatch = kind.sourceFilename.match(/\.[^.]+$/u);
                    const ext = extMatch ? extMatch[0] : ".py";
                    updateKind(i, {
                      id: newId,
                      sourceFilename: `${newId}${ext}`,
                    });
                  }}
                />
              </div>
              <div className={styles.field}>
                <label className={styles.fieldLabel}>Label</label>
                <input
                  className={styles.input}
                  value={kind.label}
                  onChange={(e) => updateKind(i, { label: e.target.value })}
                />
              </div>
            </div>

            <div className={styles.row}>
              <div className={styles.field}>
                <label className={styles.fieldLabel}>Category</label>
                <select
                  className={styles.select}
                  value={kind.category}
                  onChange={(e) =>
                    updateKind(i, { category: e.target.value as Category })
                  }
                >
                  <option value="data">data</option>
                  <option value="computation">computation</option>
                  <option value="vis_grammar">vis_grammar</option>
                  <option value="vis_simple">vis_simple</option>
                  <option value="flow">flow</option>
                </select>
              </div>
              <div className={styles.field}>
                <label className={styles.fieldLabel}>Engine</label>
                <select
                  className={styles.select}
                  value={kind.engine}
                  onChange={(e) =>
                    updateKind(i, { engine: e.target.value as Engine })
                  }
                >
                  <option value="python">python</option>
                  <option value="javascript">javascript</option>
                </select>
              </div>
            </div>

            <div className={styles.field}>
              <label className={styles.fieldLabel}>Description</label>
              <textarea
                className={styles.textarea}
                value={kind.description}
                onChange={(e) => updateKind(i, { description: e.target.value })}
              />
            </div>

            <PortEditor
              title="Input ports"
              ports={kind.inputPorts}
              onChange={(ports) => updateKind(i, { inputPorts: ports })}
            />
            <PortEditor
              title="Output ports"
              ports={kind.outputPorts}
              onChange={(ports) => updateKind(i, { outputPorts: ports })}
            />
          </div>
        ))}
      </div>

      <button className={styles.ghostButton} onClick={addKind}>
        + Add another kind
      </button>
    </div>
  );
};

const PortEditor: React.FC<{
  title: string;
  ports: PortDraft[];
  onChange: (ports: PortDraft[]) => void;
}> = ({ title, ports, onChange }) => {
  const add = () =>
    onChange([
      ...ports,
      { id: factoryUiMakeId(), types: SUPPORTED_TYPE_OPTIONS[0], cardinality: "1" },
    ]);
  const remove = (i: number) =>
    onChange(ports.filter((_, idx) => idx !== i));
  const patch = (i: number, p: Partial<PortDraft>) =>
    onChange(ports.map((port, idx) => (idx === i ? { ...port, ...p } : port)));

  return (
    <div className={styles.field}>
      <label className={styles.fieldLabel}>{title}</label>
      {ports.map((p, i) => (
        <div key={p.id} className={styles.rowTriple}>
          <input
            className={styles.input}
            value={p.types}
            placeholder="DATAFRAME, GEODATAFRAME"
            onChange={(e) => patch(i, { types: e.target.value })}
          />
          <select
            className={styles.select}
            value={p.cardinality}
            onChange={(e) => patch(i, { cardinality: e.target.value })}
          >
            {CARDINALITY_OPTIONS.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          <span />
          <button className={styles.smallButton} onClick={() => remove(i)}>
            ✕
          </button>
        </div>
      ))}
      <button className={styles.smallButton} onClick={add}>
        + Add port
      </button>
    </div>
  );
};

/* ─── Step 3: template & engine ────────────────────────────────────── */

const Step3Template: React.FC<{
  draft: Draft;
  updateKind: (i: number, patch: Partial<KindDraft>) => void;
}> = ({ draft, updateKind }) => (
  <div className={styles.panel}>
    <h2 className={styles.panelTitle}>Source per kind</h2>
    <p className={styles.panelSubtitle}>
      Each kind may ship one optional starter file. The factory writes{" "}
      <code>sources/&lt;filename&gt;</code> inside the package archive
      (extension follows the kind's engine — <code>.py</code>,{" "}
      <code>.js</code>, <code>.vl.json</code>, …). Leave the source empty
      to publish a structural kind with no starter — the editor will
      open blank when a user drops the node.
    </p>
    {draft.kinds.map((kind, i) => (
      <div key={i} className={styles.kindEntry}>
        <div className={styles.kindTitleBlock}>
          <h3 className={styles.kindTitle}>
            {kind.label.trim() || kind.id}
          </h3>
          <div className={styles.kindTitleSub}>
            {kind.id} · {kind.engine}
          </div>
        </div>
        <div className={styles.field}>
          <label className={styles.fieldLabel}>Node title</label>
          <input
            className={styles.input}
            value={kind.label}
            onChange={(e) => updateKind(i, { label: e.target.value })}
          />
          <span className={styles.fieldHint}>
            Shown in the packages palette and the node header (manifest{" "}
            <code>label</code>).
          </span>
        </div>
        <div className={styles.row}>
          <div className={styles.field}>
            <label className={styles.fieldLabel}>Editor</label>
            <select
              className={styles.select}
              value={kind.editor}
              onChange={(e) =>
                updateKind(i, { editor: e.target.value as Editor })
              }
            >
              <option value="code">code</option>
              <option value="widgets">widgets</option>
              <option value="grammar">grammar</option>
              <option value="none">none</option>
            </select>
          </div>
          <div className={styles.field}>
            <label className={styles.fieldLabel}>Source filename</label>
            <input
              className={styles.input}
              value={kind.sourceFilename}
              onChange={(e) =>
                updateKind(i, { sourceFilename: e.target.value })
              }
            />
            <span className={styles.fieldHint}>
              single safe filename — any extension (<code>.py</code>, <code>.js</code>, <code>.vl.json</code>, …).
            </span>
            {kind.sourceFilename && !SOURCE_FILENAME_RE.test(kind.sourceFilename) ? (
              <span className={styles.fieldHint} style={{ color: "var(--curio-danger-strong)" }}>
                Must match {SOURCE_FILENAME_RE.source} — no nested paths, no leading dot, must include an extension.
              </span>
            ) : null}
          </div>
        </div>

        <div className={styles.field}>
          <label className={styles.fieldLabel}>Source</label>
          <textarea
            className={styles.codeArea}
            value={kind.sourceCode}
            spellCheck={false}
            onChange={(e) =>
              updateKind(i, { sourceCode: e.target.value })
            }
          />
        </div>

        <div className={styles.row}>
          <label className={styles.checkRow}>
            <input
              type="checkbox"
              checked={kind.hasCode}
              onChange={(e) => updateKind(i, { hasCode: e.target.checked })}
            />
            hasCode
          </label>
          <label className={styles.checkRow}>
            <input
              type="checkbox"
              checked={kind.hasWidgets}
              onChange={(e) => updateKind(i, { hasWidgets: e.target.checked })}
            />
            hasWidgets
          </label>
          <label className={styles.checkRow}>
            <input
              type="checkbox"
              checked={kind.hasGrammar}
              onChange={(e) => updateKind(i, { hasGrammar: e.target.checked })}
            />
            hasGrammar
          </label>
        </div>
      </div>
    ))}
  </div>
);

/* ─── Step 4: dependencies & permissions ───────────────────────────── */

const Step4Dependencies: React.FC<{
  draft: Draft;
  update: (patch: Partial<Draft>) => void;
}> = ({ draft, update }) => {
  const togglePermission = (perm: string) => {
    const next = draft.permissions.includes(perm)
      ? draft.permissions.filter((p) => p !== perm)
      : [...draft.permissions, perm];
    update({ permissions: next });
  };

  return (
    <div className={styles.panel}>
      <h2 className={styles.panelTitle}>Dependencies and permissions</h2>
      <p className={styles.panelSubtitle}>
        Dependencies install into the shared sandbox interpreter via{" "}
        <code>/installPackages</code>. Cross-package range conflicts are
        rejected at install. Permissions are surfaced verbatim to the
        user in the install dialog (figma_mockups/02).
      </p>

      <div className={styles.field}>
        <label className={styles.fieldLabel}>Python dependencies</label>
        <DepEditor
          entries={draft.pythonDeps}
          onChange={(e) => update({ pythonDeps: e })}
          placeholder={["rasterio", "^1.3"]}
        />
      </div>

      <div className={styles.field}>
        <label className={styles.fieldLabel}>JavaScript dependencies</label>
        <DepEditor
          entries={draft.jsDeps}
          onChange={(e) => update({ jsDeps: e })}
          placeholder={["d3", "^7.0"]}
        />
      </div>

      <div className={styles.field}>
        <label className={styles.fieldLabel}>Package dependencies</label>
        <DepEditor
          entries={draft.packageDeps}
          onChange={(e) => update({ packageDeps: e })}
          placeholder={["ai.urbanlab.uhvi", "^1.0"]}
        />
        <span className={styles.fieldHint}>
          Package ids (no <code>@major</code>); the major lives in the range.
        </span>
      </div>

      <div className={styles.field}>
        <label className={styles.fieldLabel}>Permissions</label>
        {KNOWN_PERMISSIONS.map((perm) => (
          <label key={perm} className={styles.checkRow}>
            <input
              type="checkbox"
              checked={draft.permissions.includes(perm)}
              onChange={() => togglePermission(perm)}
            />
            {perm}
          </label>
        ))}
      </div>
    </div>
  );
};

const DepEditor: React.FC<{
  entries: { id: string; pkg: string; range: string }[];
  onChange: (e: { id: string; pkg: string; range: string }[]) => void;
  placeholder: [string, string];
}> = ({ entries, onChange, placeholder }) => {
  const add = () =>
    onChange([...entries, { id: factoryUiMakeId(), pkg: "", range: "" }]);
  const remove = (i: number) =>
    onChange(entries.filter((_, idx) => idx !== i));
  const patch = (
    i: number,
    p: Partial<{ pkg: string; range: string }>,
  ) =>
    onChange(
      entries.map((entry, idx) => (idx === i ? { ...entry, ...p } : entry)),
    );

  return (
    <>
      {entries.map((e, i) => (
        <div key={e.id} className={styles.rowTriple}>
          <input
            className={styles.input}
            value={e.pkg}
            placeholder={placeholder[0]}
            onChange={(ev) => patch(i, { pkg: ev.target.value })}
          />
          <input
            className={styles.input}
            value={e.range}
            placeholder={placeholder[1]}
            onChange={(ev) => patch(i, { range: ev.target.value })}
          />
          <span />
          <button className={styles.smallButton} onClick={() => remove(i)}>
            ✕
          </button>
        </div>
      ))}
      <button className={styles.smallButton} onClick={add}>
        + Add dependency
      </button>
    </>
  );
};

/* ─── Step 5: validate & publish ───────────────────────────────────── */

const Step5Publish: React.FC<{
  draft: Draft;
  busy: boolean;
  serverError: string | null;
  successInfo: string | null;
  fixtureReplace: boolean;
  setFixtureReplace: (v: boolean) => void;
  onBuild: () => void;
  onInstall: () => void;
  onPublishToCatalog: () => void;
  onGoToHub: () => void;
  forkInstallNotice: boolean;
}> = ({
  draft,
  busy,
  serverError,
  successInfo,
  fixtureReplace,
  setFixtureReplace,
  onBuild,
  onInstall,
  onPublishToCatalog,
  onGoToHub,
  forkInstallNotice,
}) => {
  const [cap, setCap] = useState<FactoryCapabilities | null>(null);
  useEffect(() => {
    let cancelled = false;
    packagesApi
      .factoryCapabilities()
      .then((r) => {
        if (!cancelled) setCap(r);
      })
      .catch(() => {
        if (!cancelled) setCap({ catalogPublish: false });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const summary = useMemo(() => {
    const kinds = draft.kinds.map((k) => `${k.id} (${k.engine}, ${k.editor})`);
    const pyDeps = draft.pythonDeps.filter((d) => d.pkg.trim());
    const jsDeps = draft.jsDeps.filter((d) => d.pkg.trim());
    const packageDeps = draft.packageDeps.filter((d) => d.pkg.trim());
    return { kinds, pyDeps, jsDeps, packageDeps };
  }, [draft]);

  return (
    <div className={styles.panel}>
      <h2 className={styles.panelTitle}>Validate and publish</h2>
      <p className={styles.panelSubtitle}>
        Submit the draft to the backend. The same validator that gates
        the install endpoint runs here, so any errors below also block
        sideloading.
      </p>
      {forkInstallNotice ? (
        <p className={styles.panelSubtitle} role="note">
          This session is a <strong>fork</strong> from an installed package — “Save and install” creates a{" "}
          <strong>new</strong> installed package at the coordinate below. The package you copied from is not modified.
        </p>
      ) : null}

      <div className={styles.field}>
        <p>
          <strong>Package id:</strong> {draft.packageId}@{draft.major}
        </p>
        <p>
          <strong>Version:</strong> {draft.version}
        </p>
        <p>
          <strong>Kinds:</strong>
          <br />
          {summary.kinds.map((k) => (
            <span key={k}>
              {k}
              <br />
            </span>
          ))}
        </p>
        {summary.pyDeps.length > 0 && (
          <p>
            <strong>Python deps:</strong>{" "}
            {summary.pyDeps.map((d) => `${d.pkg}@${d.range}`).join(", ")}
          </p>
        )}
        {summary.jsDeps.length > 0 && (
          <p>
            <strong>JS deps:</strong>{" "}
            {summary.jsDeps.map((d) => `${d.pkg}@${d.range}`).join(", ")}
          </p>
        )}
        {summary.packageDeps.length > 0 && (
          <p>
            <strong>Package deps:</strong>{" "}
            {summary.packageDeps.map((d) => `${d.pkg}@${d.range}`).join(", ")}
          </p>
        )}
        {draft.permissions.length > 0 && (
          <p>
            <strong>Permissions:</strong> {draft.permissions.join(", ")}
          </p>
        )}
      </div>

      {serverError && (
        <div className={styles.errorBox}>
          <strong>Error:</strong> {serverError}
        </div>
      )}
      {successInfo && (
        <div className={styles.successBox}>
          {successInfo}{" "}
          <button className={styles.linkButton} onClick={onGoToHub}>
            Close
          </button>
        </div>
      )}

      <div className={styles.field}>
        <p className={styles.panelSubtitle} style={{ marginTop: "1.25rem" }}>
          <strong>Catalog entry</strong> — write this package into the catalog tree under{" "}
          <code>packages/</code> for local development (commit when ready).
        </p>
        <label className={styles.checkRow}>
          <input
            type="checkbox"
            checked={fixtureReplace}
            onChange={(e) => setFixtureReplace(e.target.checked)}
            disabled={busy}
          />
          Replace existing fixture with the same package coordinate
        </label>
        {!cap?.catalogPublish && (
          <p className={styles.panelSubtitle} style={{ marginTop: "0.5rem" }}>
            Publishing is disabled (<code>CURIO_ALLOW_FACTORY_CATALOG_PUBLISH</code>{" "}
            is <code>0</code>, <code>false</code>, <code>no</code>, or <code>off</code>
            ). Unset it or set <code>1</code>, <code>true</code>, <code>yes</code>, or{" "}
            <code>on</code>, then restart the backend.
          </p>
        )}
        <div style={{ marginTop: "0.75rem" }}>
          <button
            type="button"
            className={styles.ghostButton}
            onClick={onPublishToCatalog}
            disabled={busy || !cap?.catalogPublish}
          >
            {busy ? "Working…" : "Publish to dev catalog"}
          </button>
        </div>
      </div>

      <div className={styles.footer}>
        <button className={styles.ghostButton} onClick={onBuild} disabled={busy}>
          {busy ? "Working…" : "Export .curio-package"}
        </button>
        <button
          className={styles.actionButton}
          onClick={onInstall}
          disabled={busy}
        >
          {busy ? "Working…" : "Save and install"}
        </button>
      </div>
    </div>
  );
};

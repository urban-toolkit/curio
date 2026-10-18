/**
 * The Compare Scenarios node's Difference view (#662): what it joins rows on,
 * whether it gives each difference's size (Change), and the difference itself,
 * the node's output (`utk_curio/sandbox/util/scenario_difference.py`). A
 * table's difference is shown as a table by the Vega-Lite node's code
 * (`CompareChart`), as the Chart view draws its chart. A raster's or a layer's
 * is drawn by an Autark node after this one, with the grammar's own options,
 * and the view says so.
 */
import React, { useEffect, useMemo, useState } from "react";
import NodeEmptyState from "../nodes/NodeEmptyState";
import { readGrammarInput, type GrammarInput } from "../../utils/grammarInput";
import { toRows } from "../../utils/rowSource";
import { differenceTableSpec, isDifference, type DifferenceKind } from "../../utils/compare/compareDifference";
import type { CompareDifference as DifferenceSettings } from "../../utils/compare/compareSettings";
import { CompareChart } from "./CompareChart";
import styles from "./CompareScenarios.module.css";

const LABEL = "Compare Scenarios";

/** What the view says of a raster's or a layer's difference. */
export const AUTARK_MAP_NOTE = "Draw this difference on a map with an Autark node after this one.";

type Ref = { path: string; dataType?: string };

type DifferenceRead = {
  kind: DifferenceKind | "other";
  ref: Ref;
  /** A layer's or a table's columns, in its order. */
  names: string[];
};

function rowsOf(frame: GrammarInput["frames"][number]): any[] {
  return frame.dataType === "geodataframe"
    ? (frame.payload?.features ?? []).map((feature: any) => feature?.properties ?? {})
    : toRows({ data: frame.payload });
}

/** Columns Curio keeps for its own bookkeeping, as `classifyColumns` leaves them out. */
const BOOKKEEPING = new Set(["__row_index__", "interacted"]);

function namesOf(frame: GrammarInput["frames"][number], rows: any[]): string[] {
  const names = frame.schema ? Object.keys(frame.schema) : Object.keys(rows[0] ?? {});
  return names.filter((name) => name !== frame.geometryName && !BOOKKEEPING.has(name));
}

function readOf(read: GrammarInput | null, ref: Ref): DifferenceRead | null {
  const frame = read?.frames[0];
  if (!frame) return null;
  if (frame.dataType === "raster") return { kind: "raster", ref, names: [] };
  return {
    kind: frame.dataType === "geodataframe" ? "layer" : frame.dataType === "dataframe" ? "table" : "other",
    ref: ref.dataType ? ref : { ...ref, dataType: frame.dataType },
    names: namesOf(frame, rowsOf(frame)),
  };
}

/** Read *ref* as the difference: its 100-row preview, else the whole of it. */
function useDifferenceRead(ref: Ref | null): DifferenceRead | null {
  const [read, setRead] = useState<DifferenceRead | null>(null);
  useEffect(() => {
    if (!ref) {
      setRead(null);
      return;
    }
    let current = true;
    const attempt = (preview: boolean) =>
      readGrammarInput(ref, { label: LABEL, preview, rasters: true, bundles: true }).then(
        (found) => readOf(found, ref),
        () => null,
      );
    void attempt(true)
      .then((found) => found ?? attempt(false))
      .then((found) => {
        if (current) setRead(found ?? { kind: "other", ref, names: [] });
      });
    return () => {
      current = false;
    };
  }, [ref]);
  return ref ? read : null;
}

/** The column names of each input, from its preview, for the key to join on. */
function useInputNames(refs: readonly (Ref | null)[]): string[][] | null {
  const key = JSON.stringify(refs.map((ref) => ref?.path ?? null));
  const [names, setNames] = useState<string[][] | null>(null);
  useEffect(() => {
    if (refs.length === 0 || refs.some((ref) => !ref)) {
      setNames(null);
      return;
    }
    let current = true;
    void Promise.all(
      refs.map((ref) =>
        readGrammarInput(ref, { label: LABEL, preview: true }).then(
          (found) => {
            const frame = found.frames[0];
            return frame ? namesOf(frame, rowsOf(frame)) : [];
          },
          () => [] as string[],
        ),
      ),
    ).then((found) => {
      if (current) setNames(found);
    });
    return () => {
      current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return names;
}

function Select({
  label,
  value,
  options,
  disabled,
  onChange,
}: {
  label: string;
  value: string;
  options: { value: string; text: string }[];
  disabled: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <label className={styles.field}>
      {label}
      <select
        className="nodrag nopan"
        aria-label={label}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.text}
          </option>
        ))}
      </select>
    </label>
  );
}

const AUTOMATIC_KEY = "";

/** What Change offers: the difference itself, input_1 minus input_0, or its size. */
const SIGNED = "signed";
const ABSOLUTE = "absolute";
const CHANGE_OPTIONS = [
  { value: SIGNED, text: "Signed" },
  { value: ABSOLUTE, text: "Absolute" },
];

export function CompareDifference({
  nodeData,
  output,
  inputRefs,
  rastersIn,
  settings,
  editable,
  dashboardOn,
  connected,
  runError,
  onChange,
}: {
  nodeData: any;
  /** The node's output, the difference once it has run in Difference. */
  output: Ref | null;
  /** What each wired input circle holds, in circle order. */
  inputRefs: readonly (Ref | null)[];
  /** Whether the inputs are rasters, which are not joined on a key. */
  rastersIn: boolean;
  settings: DifferenceSettings | undefined;
  editable: boolean;
  dashboardOn: boolean;
  connected: boolean;
  runError: string | null;
  onChange: (next: DifferenceSettings) => void;
}) {
  const read = useDifferenceRead(output);
  const inputNames = useInputNames(rastersIn || dashboardOn ? [] : inputRefs);
  const common = useMemo(() => {
    if (!inputNames || inputNames.length !== 2) return [];
    const [first, second] = inputNames;
    return first.filter((name) => second.includes(name));
  }, [inputNames]);

  const drawn = read && isDifference(read.kind, read.names) ? read : null;
  const kind = drawn?.kind ?? null;

  const set = (patch: Partial<DifferenceSettings>) => {
    const next: DifferenceSettings = { ...(settings ?? {}), ...patch };
    for (const field of Object.keys(next) as (keyof DifferenceSettings)[]) {
      if (!next[field]) delete next[field];
    }
    onChange(next);
  };

  const keyOptions = [
    { value: AUTOMATIC_KEY, text: "osm_id, building_id, or the shapes" },
    ...[...new Set([...(settings?.key ? [settings.key] : []), ...common])].map((name) => ({ value: name, text: name })),
  ];

  let stage: React.ReactNode;
  if (runError !== null) {
    stage = (
      <p className={`nodrag nopan ${styles.problem}`} data-compare-run-error="true">
        {runError}
      </p>
    );
  } else if (!connected) {
    stage = <NodeEmptyState reason="disconnected" hint="Connect two scenarios' outcomes: input_0 is the reference, input_1 the comparison." />;
  } else if (!output) {
    stage = <NodeEmptyState reason="not-run" hint="Run this node to subtract input_0 from input_1." />;
  } else if (!read) {
    stage = <NodeEmptyState reason="not-run" hint="Reading the difference." />;
  } else if (!drawn) {
    stage = <NodeEmptyState reason="not-run" hint="Run this node again to compute the difference." />;
  } else if (drawn.kind === "table") {
    stage = <CompareChart nodeData={nodeData} stacked={drawn.ref} specText={JSON.stringify(differenceTableSpec(drawn.names))} />;
  } else {
    stage = (
      <p className={`nodrag nopan ${styles.note}`} data-compare-difference-map="autark">
        {AUTARK_MAP_NOTE}
      </p>
    );
  }

  return (
    <div className={styles.chart} data-compare-difference={kind ?? "none"}>
      {!dashboardOn ? (
        <div className={styles.bar}>
          {!rastersIn ? (
            <Select
              label="Key"
              value={settings?.key ?? AUTOMATIC_KEY}
              disabled={!editable}
              options={keyOptions}
              onChange={(key) => set({ key })}
            />
          ) : null}
          <Select
            label="Change"
            value={settings?.absolute ? ABSOLUTE : SIGNED}
            disabled={!editable}
            options={CHANGE_OPTIONS}
            onChange={(next) => set({ absolute: next === ABSOLUTE })}
          />
        </div>
      ) : null}
      <div className={styles.mapCanvas}>{stage}</div>
    </div>
  );
}

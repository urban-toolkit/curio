/**
 * The Compare Scenarios node's Difference view (#662): what it joins rows on
 * and what its map colors by, and the difference itself, the node's output
 * (`utk_curio/sandbox/util/scenario_difference.py`). A raster or a layer is
 * drawn on a map by the Autark node's map code (`CompareMap`), a table by the
 * Vega-Lite node's (`CompareChart`), as the Chart view draws its chart.
 */
import React, { Suspense, useEffect, useMemo, useState } from "react";
import NodeEmptyState from "../nodes/NodeEmptyState";
import { readGrammarInput, type GrammarInput } from "../../utils/grammarInput";
import { toRows } from "../../utils/rowSource";
import { classifyColumns, type ClassifiedColumn } from "../../utils/starterSpec";
import {
  differenceMapDoc,
  differenceTableSpec,
  differenceValues,
  isDifference,
  resolveValue,
  type DifferenceKind,
} from "../../utils/compare/compareDifference";
import type { CompareDifference as DifferenceSettings } from "../../utils/compare/compareSettings";
import { CompareChart } from "./CompareChart";
import styles from "./CompareScenarios.module.css";

const LABEL = "Compare Scenarios";

/** The map's code loads only when a difference is drawn on one. */
const CompareMap = React.lazy(() => import("./CompareMap"));

type Ref = { path: string; dataType?: string };

type DifferenceRead = {
  kind: DifferenceKind | "other";
  ref: Ref;
  /** A raster's bands. */
  bands: string[];
  /** A layer's or a table's columns, in its order, and their roles. */
  names: string[];
  columns: ClassifiedColumn[];
};

function bandsOf(payload: any): string[] {
  const bands = payload?.envelope?.data?.features?.[0]?.properties?.bands;
  return Array.isArray(bands) && bands.length > 0 ? bands.map((band: any) => String(band.id)) : ["band_1"];
}

function rowsOf(frame: GrammarInput["frames"][number]): any[] {
  return frame.dataType === "geodataframe"
    ? (frame.payload?.features ?? []).map((feature: any) => feature?.properties ?? {})
    : toRows({ data: frame.payload });
}

function namesOf(frame: GrammarInput["frames"][number], rows: any[]): string[] {
  const names = frame.schema ? Object.keys(frame.schema) : Object.keys(rows[0] ?? {});
  return names.filter((name) => name !== frame.geometryName);
}

function readOf(read: GrammarInput | null, ref: Ref): DifferenceRead | null {
  const frame = read?.frames[0];
  if (!frame) return null;
  if (frame.dataType === "raster") return { kind: "raster", ref, bands: bandsOf(frame.payload), names: [], columns: [] };
  const rows = rowsOf(frame);
  const names = namesOf(frame, rows);
  return {
    kind: frame.dataType === "geodataframe" ? "layer" : frame.dataType === "dataframe" ? "table" : "other",
    ref: ref.dataType ? ref : { ...ref, dataType: frame.dataType },
    bands: [],
    names,
    columns: classifyColumns(frame.schema, rows, frame.geometryName),
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
        if (current) setRead(found ?? { kind: "other", ref, bands: [], names: [], columns: [] });
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
  const values = kind === "raster" || kind === "layer" ? differenceValues(kind, drawn!) : [];
  const value = resolveValue(settings?.value, values);

  const set = (patch: Partial<DifferenceSettings>) => {
    const next: DifferenceSettings = { ...(settings ?? {}), ...patch };
    for (const field of Object.keys(next) as (keyof DifferenceSettings)[]) {
      if (!next[field]) delete next[field];
    }
    onChange(next);
  };

  const keyOptions = [
    { value: AUTOMATIC_KEY, text: "osm_id or building_id" },
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
    stage = <NodeEmptyState reason="disconnected" hint="Connect two scenarios' outcomes: input 0 is the reference, input 1 the comparison." />;
  } else if (!output) {
    stage = <NodeEmptyState reason="not-run" hint="Run this node to subtract input 0 from input 1." />;
  } else if (!read) {
    stage = <NodeEmptyState reason="not-run" hint="Reading the difference." />;
  } else if (!drawn) {
    stage = <NodeEmptyState reason="not-run" hint="Run this node again to compute the difference." />;
  } else if (drawn.kind === "table") {
    stage = <CompareChart nodeData={nodeData} stacked={drawn.ref} specText={JSON.stringify(differenceTableSpec(drawn.names))} />;
  } else {
    const docText = JSON.stringify(differenceMapDoc(drawn.kind as "raster" | "layer", value));
    stage = (
      <Suspense fallback={<NodeEmptyState reason="not-run" hint="Loading the map." />}>
        <CompareMap nodeId={nodeData.nodeId} difference={drawn.ref} docText={docText} />
      </Suspense>
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
          {values.length > 0 ? (
            <Select
              label="Color by"
              value={value?.value ?? ""}
              disabled={!editable}
              options={values.map((option) => ({ value: option.value, text: option.text }))}
              onChange={(next) => set({ value: next })}
            />
          ) : null}
        </div>
      ) : null}
      <div className={styles.mapCanvas}>{stage}</div>
      {drawn && drawn.kind !== "table" && value && !value.categorical ? (
        <p className={styles.note} data-compare-difference-note="true">
          Red is the lowest difference and blue the highest; the middle color is halfway between them, not zero.
        </p>
      ) : null}
    </div>
  );
}

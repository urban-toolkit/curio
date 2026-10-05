/**
 * The Compare Scenarios node's chart (#662): its stacked table, drawn by the
 * Vega-Lite node's own code (`useVega`) into the node's `vega<nodeId>` mount,
 * as a chart node draws its input. The rows it reads are the node's own
 * output, which the node's run has already handed downstream, and the
 * provenance of the node is its code, so the chart neither forwards its rows
 * nor records a version.
 *
 * Mounted once the node has an output, so the mount exists when `useVega`
 * starts watching its size.
 */
import React, { useEffect, useMemo, useState } from "react";
import { useVega } from "../../hook/useVega";
import { renderOutcome } from "../../utils/renderOutcome";
import styles from "./CompareScenarios.module.css";

export function CompareChart({
  nodeData,
  stacked,
  specText,
}: {
  /** The node's data, whose `input` the chart replaces with the node's output. */
  nodeData: any;
  /** The node's output: the stacked table's reference. */
  stacked: { path: string; dataType?: string };
  specText: string;
}) {
  const data = useMemo(() => ({ ...nodeData, input: stacked }), [nodeData, stacked]);
  const { handleCompileGrammar } = useVega({
    data,
    code: specText,
    connected: true,
    hasSpec: true,
    recordsProvenance: false,
    forwardsInput: false,
  });
  // What the compile of this spec over this table came to. Keyed, so a new
  // spec or table reads as drawing until its own compile settles.
  const key = `${stacked.path}|${specText}`;
  const [settled, setSettled] = useState<{ key: string; problem: string | null } | null>(null);

  useEffect(() => {
    let current = true;
    handleCompileGrammar(specText)
      .then((counts) => {
        if (!current) return;
        const outcome = renderOutcome(counts ?? {});
        setSettled({ key, problem: outcome.empty ? outcome.message : null });
      })
      .catch((error: any) => {
        if (current) setSettled({ key, problem: String(error?.message ?? error) });
      });
    return () => {
      current = false;
    };
  }, [stacked, specText]);

  const problem = settled?.key === key ? settled.problem : null;
  const state = settled?.key !== key ? "drawing" : problem ? "problem" : "drawn";

  return (
    <div className={styles.chart} data-compare-chart-state={state}>
      <div
        id={"vega" + nodeData.nodeId}
        className={`nodrag nowheel curio-vega-mount ${styles.mount}`}
        data-compare-chart="true"
      />
      {problem ? (
        <p className={styles.problem} data-compare-chart-problem="true">
          {problem}
        </p>
      ) : null}
    </div>
  );
}

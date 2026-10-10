/**
 * The Vega-Lite node's strip above its chart while it compares scenarios (its
 * Compare scenarios switch, in Node settings, on): each scenario on its circle,
 * ticked when its input has every column the spec reads, crossed in red when
 * it lacks one, which its tooltip names (utils/vegaCompare).
 */
import React from "react";
import type { ScenarioRequirement } from "../../utils/vegaCompare";

const MISSING = "#c0392b";
const PRESENT = "#1e7f4f";

export function VegaCompareStrip({ rows }: { rows: readonly ScenarioRequirement[] }) {
  return (
    <div
      className="nodrag nowheel"
      data-vega-compare-strip
      style={{
        fontSize: 11, textAlign: "left", padding: "4px 8px", borderBottom: "1px solid #e3e3e3",
        maxHeight: 64, overflowY: "auto", flex: "0 0 auto", display: "flex", flexWrap: "wrap", gap: "2px 12px",
      }}
    >
      {rows.map((row) => {
        const waiting = row.columns === null;
        const lacks = row.missing.length > 0;
        return (
          <span
            key={row.slot}
            data-vega-compare-row={row.slot}
            data-ok={waiting ? undefined : lacks ? "false" : "true"}
            data-missing={row.missing.join(",")}
            title={waiting
              ? `input_${row.slot} · ${row.label.name}: waiting for its input`
              : lacks
                ? `input_${row.slot} · ${row.label.name} is missing: ${row.missing.join(", ")}`
                : `input_${row.slot} · ${row.label.name} has what the chart needs`}
            style={{ display: "inline-flex", alignItems: "center", gap: 4, color: lacks ? MISSING : undefined }}
          >
            <span style={{ width: 9, height: 9, borderRadius: "50%", background: row.label.color, flex: "0 0 auto" }} />
            <span style={{ fontWeight: 600 }}>{row.label.name}</span>
            {waiting ? null : <span style={{ color: lacks ? MISSING : PRESENT, fontWeight: 700 }}>{lacks ? "✗" : "✓"}</span>}
          </span>
        );
      })}
    </div>
  );
}

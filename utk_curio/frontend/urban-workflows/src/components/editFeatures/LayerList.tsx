/**
 * The layers the Map Edits node is fed (#662), as cards grouped by the
 * geometry their features have (points, lines, areas): the name, where it
 * came from and how many features it holds, and its properties. + New data
 * layer starts a layer of the node's own.
 */
import React, { useMemo } from "react";
import type { FeatureEdit } from "../../utils/editFeatures/editFeatures";
import {
  GEOMETRY_KIND,
  KIND_GEOMETRY,
  KIND_LABEL,
  KIND_NOUN,
  geometryKinds,
  propertiesFor,
  withAddedColumns,
  type GeometryKind,
} from "../../utils/editFeatures/layerModel";
import type { WorkbenchLayer } from "./LayerWorkbench";
import { KindIcon, plural } from "./workbenchParts";
import styles from "./EditFeatures.module.css";

export default function LayerList({
  layers,
  edits,
  nodeLayer,
  writable,
  onOpen,
  onNewLayer,
}: {
  layers: WorkbenchLayer[];
  edits: readonly FeatureEdit[];
  /** The layer the log's edits apply to when they name none. */
  nodeLayer: string | null;
  writable: boolean;
  /** Opens the layer *name*: what can be done with it. */
  onOpen: (name: string) => void;
  /** Opens the builder of a new layer. */
  onNewLayer: () => void;
}) {
  const grouped = useMemo(() => {
    const groups = new Map<GeometryKind, WorkbenchLayer[]>();
    for (const layer of layers) {
      const kinds = layer.newLayer ? [GEOMETRY_KIND[layer.newLayer.geometry]] : geometryKinds(layer.fc).map((k) => k.kind);
      for (const k of kinds) {
        const list = groups.get(k) ?? [];
        if (!list.includes(layer)) list.push(layer);
        groups.set(k, list);
      }
    }
    return (["points", "lines", "areas"] as GeometryKind[]).filter((k) => groups.has(k)).map((k) => ({ kind: k, layers: groups.get(k) as WorkbenchLayer[] }));
  }, [layers]);

  const countOf = (layer: WorkbenchLayer) =>
    layer.newLayer ? edits.filter((e) => e.op === "add" && e.layer === layer.name && e.enabled !== false).length : (layer.fc.features ?? []).length;

  return (
    <div className={styles.group} data-testid="interaction-layers">
      <span className={styles.lead}>
        {layers.length === 0 ? (
          "No layers yet."
        ) : (
          <>
            Found <b>{plural(layers.length, "layer", "layers")}</b>
            {grouped.length > 1 ? (
              <>
                {" "}in <b>{grouped.length} geometry types</b>
              </>
            ) : null}
            . Pick a layer to work on:
          </>
        )}
      </span>
      {grouped.map((group) => (
        <div key={group.kind} className={styles.group}>
          <span className={styles.groupLabel}>
            <KindIcon kind={group.kind} />
            {KIND_LABEL[group.kind]} · {KIND_GEOMETRY[group.kind]}
          </span>
          {group.layers.map((layer) => {
            const n = countOf(layer);
            const columns = layer.newLayer
              ? (layer.newLayer.properties ?? []).map((p) => p.name)
              : withAddedColumns(propertiesFor(layer.fc, layer.key), edits, layer.name, nodeLayer).map((p) => p.name);
            return (
              <button
                key={layer.name}
                type="button"
                data-testid={`interaction-layer-${layer.name}`}
                className={`nodrag nopan ${styles.layerCard}`}
                onClick={() => onOpen(layer.name)}
              >
                <span className={styles.cardTop}>
                  <span className={styles.cardName}>
                    {layer.label} {layer.newLayer ? <span className={styles.badge}>new</span> : null}
                  </span>
                  <span className={styles.meta}>
                    {layer.newLayer ? "new layer" : layer.table ?? layer.name} · {plural(n, KIND_NOUN[group.kind], `${KIND_NOUN[group.kind]}s`)}
                  </span>
                </span>
                <span className={styles.props}>
                  {columns.length > 0 ? `properties: ${columns.slice(0, 8).join(", ")}${columns.length > 8 ? ", …" : ""}` : "no properties"}
                  {!layer.key && !layer.newLayer ? " · no id column" : ""}
                </span>
              </button>
            );
          })}
        </div>
      ))}
      {writable ? (
        <div className={styles.footer}>
          <button type="button" data-testid="interaction-new-layer-open" className={`nodrag nopan ${styles.button}`} onClick={onNewLayer}>
            + New data layer
          </button>
          <span className={styles.hint}>Starts a layer of your own, with its own properties.</span>
        </div>
      ) : null}
      {grouped.length > 1 ? <span className={styles.hint}>A layer with mixed geometry is listed under each kind, so each list only offers the tools that fit it.</span> : null}
    </div>
  );
}

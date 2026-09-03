import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useEdges, useReactFlow } from 'reactflow';
import { NodeBehaviorHook } from '../../registry/types';
import { fetchData } from '../../services/api';
import { resolveNodeDisplayLabel } from '../../utils/palettePackageFactoryDraft';
import { triggerBlobDownload } from '../../utils/triggerBlobDownload';
import {
  EXPORT_MIME,
  ExportTarget,
  resolveExportTarget,
} from '../../utils/dataExportTarget';
import OutputContent from '../../components/editing/OutputContent';

/**
 * Turn a sandbox payload into the bytes of its file.
 *
 * Kept apart from the node so the shape rules are readable: a dataframe is a
 * column-major dict, a geodataframe is already a FeatureCollection, and
 * anything else is handed over as JSON because there is nothing better to make
 * of it.
 */
function serialize(result: any, format: ExportTarget['format']): string {
  if (format === 'csv') {
    const rows: string[] = [];
    if (result?.dataType === 'dataframe' && result?.data) {
      const columns = Object.keys(result.data);
      const count = columns.length ? Object.keys(result.data[columns[0]] ?? {}).length : 0;
      rows.push(columns.join(','));
      for (let i = 0; i < count; i++) {
        rows.push(columns.map((col) => JSON.stringify(result.data[col][i] ?? '')).join(','));
      }
      return rows.join('\n');
    }
    if (result?.dataType === 'geodataframe' && result?.data?.features?.length) {
      const properties = result.data.features.map((f: any) => ({
        ...f.properties,
        geometry: JSON.stringify(f.geometry),
      }));
      const columns = Object.keys(properties[0]);
      rows.push(columns.join(','));
      for (const row of properties) {
        rows.push(columns.map((col) => JSON.stringify(row[col] ?? '')).join(','));
      }
      return rows.join('\n');
    }
    return '';
  }
  return JSON.stringify(result?.data);
}

/**
 * Data Export: one button that names the file it will give you.
 *
 * It used to be an "Export format" dropdown plus a run: the user picked between
 * CSV / JSON / GeoJSON, pressed play, and got a file called ``data_export``
 * whatever the input was (#226). Both halves were avoidable. The format is
 * already determined by the payload on the wire -- offering CSV for a raster is
 * a choice that can only fail -- and the name is already known from the input,
 * so writing every export to the same stem meant three exports overwrote each
 * other in the download folder.
 *
 * The format was also never persisted (plain ``useState``), so a chosen format
 * was silently lost on reload. That is why this needs no migration: there is no
 * saved value anywhere to carry forward.
 */
export const useDataExportBehavior: NodeBehaviorHook = (data, nodeState) => {
  const [busy, setBusy] = useState(false);

  const input = data.input && typeof data.input === 'object' ? (data.input as any) : null;
  const connected = Boolean(input?.path);

  // The name of whatever produced the input, used when the payload carries no
  // dataset filename of its own.
  //
  // This used to read ``datasetSource`` off the export node's own data, which
  // never resolved: that field is written by the dataset palette onto the node
  // it creates, and an export node is never created that way. So the ordinary
  // case — a compute node wired into Data Export — always fell through to the
  // default stem and the button read "Download data_export.csv" (#226). Name the
  // node actually feeding this one instead, which is what the button should have
  // said all along.
  const edges = useEdges();
  const upstreamId = useMemo(
    () => edges.find((edge) => edge.target === data.nodeId)?.source ?? null,
    [edges, data.nodeId],
  );
  const { getNode } = useReactFlow();
  const sourceName = useMemo(() => {
    // A dataset dropped straight onto this node still wins, when it is there.
    const own = (data as { datasetSource?: { title?: unknown } }).datasetSource;
    if (typeof own?.title === 'string' && own.title.trim()) return own.title;
    if (!upstreamId) return null;
    const upstream = getNode(upstreamId);
    if (!upstream?.data) return null;
    const fromPalette = (upstream.data as { datasetSource?: { title?: unknown } })
      .datasetSource;
    if (typeof fromPalette?.title === 'string' && fromPalette.title.trim()) {
      return fromPalette.title;
    }
    try {
      return resolveNodeDisplayLabel(upstream.data as any);
    } catch {
      // An unresolvable node type is not worth failing a download over.
      return null;
    }
  }, [data, upstreamId, getNode]);

  const target = useMemo(
    () => resolveExportTarget(input, sourceName),
    [input?.dataType, input?.dataset, sourceName],
  );

  const download = useCallback(async () => {
    if (!connected || busy) return;
    setBusy(true);
    nodeState.setOutput({ code: 'exec', content: '', outputType: target.format });
    try {
      const result: any = await fetchData(input.path);
      const contents = serialize(result, target.format);
      // Shared helper rather than a hand-rolled anchor: it revokes the object
      // URL, which the inline version here never did.
      triggerBlobDownload(
        new Blob([contents], { type: EXPORT_MIME[target.format] }),
        target.filename,
      );
      nodeState.setOutput({
        code: 'success',
        content: `Downloaded ${target.filename}`,
        outputType: target.format,
      });
    } catch (err) {
      // Reported on the node instead of only in the console, which is where a
      // failed export used to go.
      nodeState.setOutput({
        code: 'error',
        content: `Could not export: ${(err as Error)?.message ?? 'unknown error'}`,
        outputType: target.format,
      });
    } finally {
      setBusy(false);
    }
  }, [connected, busy, input, target, nodeState]);

  const customWidgetsCallback = useCallback(
    (div: HTMLElement) => {
      div.replaceChildren();

      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'nodrag nowheel';
      button.disabled = !connected || busy;
      // The filename IS the format indicator: showing "boundaries.geojson"
      // says what will arrive without a control that implies a choice.
      button.textContent = connected ? `Download ${target.filename}` : 'Download';
      button.title = connected
        ? `Download this node's input as ${target.filename}`
        : 'Connect a dataset to export it';
      button.setAttribute('aria-label', button.textContent);
      button.addEventListener('click', (event) => {
        event.preventDefault();
        void download();
      });
      div.appendChild(button);

      if (!connected) {
        const hint = document.createElement('span');
        hint.textContent = 'Connect a dataset to export it';
        hint.style.marginLeft = '8px';
        hint.style.fontSize = '11px';
        hint.style.opacity = '0.75';
        div.appendChild(hint);
      }
    },
    [connected, busy, target.filename, download],
  );

  useEffect(() => {
    nodeState.setOutput({ code: 'success', content: '', outputType: target.format });
  }, [data.input, target.format]);

  const contentComponent = useMemo(
    () => <OutputContent output={nodeState.output} />,
    [nodeState.output],
  );

  return {
    // Play still works and does the same thing, so a Run All over a dataflow
    // that ends in an export behaves as it did.
    sendCodeOverride: download,
    setSendCodeCallbackOverride: () => {},
    customWidgetsCallback,
    contentComponent,
  };
};

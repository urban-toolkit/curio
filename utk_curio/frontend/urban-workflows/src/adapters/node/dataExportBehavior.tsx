import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useEdges, useReactFlow } from 'reactflow';
import { useFlowContext } from '../../providers/FlowProvider';
import { NodeBehaviorHook } from '../../registry/types';
import { fetchData } from '../../services/api';
import { resolveNodeDisplayLabel } from '../../utils/palettePackageFactoryDraft';
import { triggerBlobDownload } from '../../services/packages';
import {
  EXPORT_MIME,
  ExportTarget,
  resolveExportTarget,
} from '../../utils/dataExportTarget';

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
 * Data Export: the node is one Download button that names the file (#226).
 *
 * It has no code, no widgets and no play button, and a Run All never
 * downloads. The button downloads the input the node has. When it has none
 * yet, the button runs the nodes upstream first, the way the play button
 * used to, and downloads once that run is over.
 *
 * The format follows the payload on the wire and the name follows the input,
 * so there is nothing to choose.
 */
export const useDataExportBehavior: NodeBehaviorHook = (data, nodeState) => {
  const [busy, setBusy] = useState(false);
  // Set by a click that had to run the upstream nodes first; the download
  // fires when that run is over.
  const [pendingDownload, setPendingDownload] = useState(false);
  const sawRunRef = useRef(false);
  const { playNodesUpTo, isRunActive } = useFlowContext();

  const input = data.input && typeof data.input === 'object' ? (data.input as any) : null;
  const hasInput = Boolean(input?.path);

  // The name of whatever produced the input, used when the payload carries no
  // dataset filename of its own.
  const edges = useEdges();
  const upstreamId = useMemo(
    () => edges.find((edge) => edge.target === data.nodeId)?.source ?? null,
    [edges, data.nodeId],
  );
  const wired = upstreamId != null;
  const { getNode } = useReactFlow();
  const sourceName = useMemo(() => {
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
  }, [upstreamId, getNode]);

  const target = useMemo(
    () => resolveExportTarget(input, sourceName),
    [input?.dataType, input?.dataset, sourceName],
  );

  const download = useCallback(async () => {
    if (busy) return;
    if (!hasInput) {
      nodeState.setOutput({
        code: 'error',
        content: 'Could not export: the connected node produced no output.',
      });
      return;
    }
    setBusy(true);
    nodeState.setOutput({ code: 'exec', content: '', outputType: target.format });
    try {
      const result: any = await fetchData(input.path);
      const contents = serialize(result, target.format);
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
      nodeState.setOutput({
        code: 'error',
        content: `Could not export: ${(err as Error)?.message ?? 'unknown error'}`,
        outputType: target.format,
      });
    } finally {
      setBusy(false);
    }
  }, [busy, hasInput, input, target, nodeState]);

  const onClick = useCallback(() => {
    if (busy || pendingDownload || !wired) return;
    if (hasInput) {
      void download();
      return;
    }
    sawRunRef.current = false;
    setPendingDownload(true);
    nodeState.setOutput({ code: 'exec', content: '' });
    playNodesUpTo(data.nodeId);
  }, [busy, pendingDownload, wired, hasInput, download, nodeState, playNodesUpTo, data.nodeId]);

  // The upstream run a click started: download when it is over.
  useEffect(() => {
    if (!pendingDownload) return;
    if (isRunActive) {
      sawRunRef.current = true;
      return;
    }
    if (!sawRunRef.current && !hasInput) return;
    sawRunRef.current = false;
    setPendingDownload(false);
    void download();
  }, [pendingDownload, isRunActive, hasInput, download]);

  const waiting = busy || pendingDownload;
  const label = hasInput ? `Download ${target.filename}` : 'Download';
  const title = !wired
    ? 'Connect a dataset to export it'
    : hasInput
      ? `Download this node's input as ${target.filename}`
      : 'Runs the connected node, then downloads its output';

  // One line under the button: what is missing, what is running, or what the
  // last click did. No output panel, the node is only the button.
  const output = nodeState.output;
  const statusText = !wired
    ? 'Connect a dataset to export it'
    : pendingDownload
      ? 'Running the connected node...'
      : output?.code === 'exec'
        ? 'Downloading...'
        : output?.code === 'success' || output?.code === 'error'
          ? String(output.content ?? '')
          : '';
  const statusIsError = wired && !pendingDownload && output?.code === 'error';

  const contentComponent = useMemo(
    () => (
      <div
        className="nodrag nowheel"
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          gap: '8px',
          height: '100%',
          padding: '8px',
          overflow: 'hidden',
        }}
      >
        <button
          type="button"
          className="btn btn-outline-secondary btn-sm nodrag nowheel"
          disabled={!wired || waiting}
          title={title}
          aria-label={label}
          onClick={onClick}
          style={{ maxWidth: '100%', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
        >
          {label}
        </button>
        {statusText ? (
          <span
            role="status"
            style={{
              fontSize: '11px',
              opacity: statusIsError ? 1 : 0.75,
              color: statusIsError ? 'var(--curio-danger-text)' : undefined,
              textAlign: 'center',
            }}
          >
            {statusText}
          </span>
        ) : null}
      </div>
    ),
    [wired, waiting, title, label, onClick, statusText, statusIsError],
  );

  return { contentComponent };
};

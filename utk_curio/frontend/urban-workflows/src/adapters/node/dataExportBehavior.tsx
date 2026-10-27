import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useEdges, useReactFlow } from 'reactflow';
import { useFlowContext } from '../../providers/FlowProvider';
import { NodeBehaviorHook } from '../../registry/types';
import { fetchData } from '../../services/api';
import { fetchOutputFile } from '../../services/outputFiles';
import { resolveNodeDisplayLabel } from '../../utils/palettePackageFactoryDraft';
import { triggerBlobDownload } from '../../services/packages';
import { exportDownloadName } from '../../utils/dataExportTarget';
import { runKeyOf } from '../../utils/references/runKeys';

/** What the Download button last did, under it. */
type Status = { text: string; error?: boolean } | null;

/** The file an output names: its artifact id, and the text it holds once read. */
type NamedFile = { path: string; value: string | null };

/**
 * Data Export: its Python code writes the file (`curio_export`), and a
 * Download button under its File name saves it.
 *
 * The node runs as any code node runs, on its play, a Run All or a change of
 * File name, and its output is the name of the file it wrote; a Run All writes
 * the file and never downloads it. The button sits on the Widgets tab the node
 * opens on, under its widgets' rows, and on its dashboard tile under the tile's
 * controls (`controlsComponent`; NodeEditor, WidgetsEditor), and downloads the
 * file the node's output names, through `/output-file`. A node with no current result first
 * runs, with the nodes before it, and the button downloads the file that run
 * wrote. The download keeps the file's name; a file named by default (File
 * name left empty) is named after what feeds the node (utils/dataExportTarget).
 */
export const useDataExportBehavior: NodeBehaviorHook = (data, nodeState) => {
  const {
    playNodesUpTo, isRunActive: browserRunActive, serverRunActive, outputs,
  } = useFlowContext();
  const isRunActive = Boolean(browserRunActive || serverRunActive);

  // The output this node's last run stored: the name of the file it wrote.
  const ownOutput = useMemo(
    () => (Array.isArray(outputs) ? outputs : []).find((o) => o?.nodeId === data.nodeId)?.output as any,
    [outputs, data.nodeId],
  );
  const outputPath = typeof ownOutput?.path === 'string' && ownOutput.path ? (ownOutput.path as string) : null;
  const outputCode = nodeState.output?.code ?? '';

  const [busy, setBusy] = useState(false);
  // Set by a click that had to run the node first; the download comes when
  // that run is over.
  const [pending, setPending] = useState(false);
  const sawRunRef = useRef(false);
  const pathBeforeRef = useRef<string | null>(null);
  const [status, setStatus] = useState<Status>(null);

  // The name of whatever feeds the node, which names a file named by default
  // when its input carries no dataset name.
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
  const input = data.input && typeof data.input === 'object' ? (data.input as any) : null;

  // The text the output holds: the file's name, or its path.
  const [named, setNamed] = useState<NamedFile | null>(null);
  const readName = useCallback(async (path: string): Promise<string | null> => {
    const read: any = await fetchData(path);
    const value = read?.dataType === 'str' && typeof read?.data === 'string' ? (read.data as string) : null;
    setNamed({ path, value });
    return value;
  }, []);
  useEffect(() => {
    if (outputCode !== 'success' || !outputPath || named?.path === outputPath) return;
    readName(outputPath).catch(() => setNamed({ path: outputPath, value: null }));
  }, [outputCode, outputPath, named?.path, readName]);
  const fileValue = named && named.path === outputPath ? named.value : null;
  const downloadName = fileValue ? exportDownloadName(fileValue, input, sourceName) : '';

  const download = useCallback(async (path: string) => {
    setBusy(true);
    setStatus({ text: 'Downloading...' });
    try {
      const value = named?.path === path ? named.value : await readName(path);
      const fetched = await fetchOutputFile(path);
      if (!fetched.ok) {
        setStatus({ text: `Could not export: ${fetched.message}`, error: true });
        return;
      }
      const name = exportDownloadName(value, input, sourceName) || 'data_export';
      triggerBlobDownload(fetched.blob, name);
      setStatus({ text: `Downloaded ${name}` });
    } catch (err) {
      setStatus({ text: `Could not export: ${(err as Error)?.message ?? 'unknown error'}`, error: true });
    } finally {
      setBusy(false);
    }
  }, [named, readName, input, sourceName]);

  const onClick = useCallback(() => {
    if (busy || pending || !wired) return;
    // The result is current when the node's last run succeeded with the code,
    // widgets and selections it holds now (useNodeState stamps the run key).
    const current = outputCode === 'success' && outputPath != null
      && (data as { executedCode?: string }).executedCode === runKeyOf(
        nodeState.code ?? '', (data as any).widgets, (data as any).selections,
      );
    if (current) {
      void download(outputPath);
      return;
    }
    pathBeforeRef.current = outputPath;
    sawRunRef.current = false;
    setPending(true);
    setStatus({ text: 'Running the node...' });
    playNodesUpTo(data.nodeId);
  }, [busy, pending, wired, outputCode, outputPath, data, nodeState.code, download, playNodesUpTo]);

  // The run a click started: download the file it wrote once it is over. A
  // run that ends without a new result of this node's hands out nothing.
  useEffect(() => {
    if (!pending) return;
    if (isRunActive) {
      sawRunRef.current = true;
      return;
    }
    if (!sawRunRef.current || outputCode === 'exec') return;
    sawRunRef.current = false;
    setPending(false);
    if (outputCode === 'success' && outputPath && outputPath !== pathBeforeRef.current) {
      void download(outputPath);
    } else if (outputCode === 'error') {
      setStatus({ text: 'Could not export: the node failed.', error: true });
    } else {
      setStatus({ text: 'Could not export: the run did not reach this node.', error: true });
    }
  }, [pending, isRunActive, outputCode, outputPath, download]);

  const waiting = busy || pending;
  const label = downloadName ? `Download ${downloadName}` : 'Download';
  const title = !wired
    ? 'Connect a dataset to export it'
    : downloadName
      ? `Download the file this node wrote as ${downloadName}`
      : 'Runs this node and the nodes before it, then downloads the file it writes';
  const shown: Status = !wired ? { text: 'Connect a dataset to export it' } : status;

  const controlsComponent = useMemo(
    () => (
      <div
        className="nodrag nowheel"
        style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '4px', maxWidth: '240px' }}
      >
        <button
          type="button"
          className="btn btn-outline-secondary btn-sm nodrag nowheel"
          data-download-button="true"
          disabled={!wired || waiting}
          data-tooltip={title}
          aria-label={label}
          onClick={onClick}
          style={{ maxWidth: '100%', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
        >
          {label}
        </button>
        {shown ? (
          <span
            role="status"
            style={{
              fontSize: '11px',
              maxWidth: '100%',
              opacity: shown.error ? 1 : 0.75,
              color: shown.error ? 'var(--curio-danger-text)' : undefined,
              textAlign: 'right',
            }}
          >
            {shown.text}
          </span>
        ) : null}
      </div>
    ),
    [wired, waiting, title, label, onClick, shown?.text, shown?.error],
  );

  return { controlsComponent };
};

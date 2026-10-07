/**
 * A dataflow file File > Load picked, on its way to the dataflow it opens as.
 *
 * A loaded file is a dataflow of its own (#751): its first save creates a
 * project named after it, and the dataflow that was open keeps its nodes, its
 * name, its packages and its datasets. So the menu leaves the open dataflow
 * the way File > New does, hands the parsed spec over here and goes to
 * `/dataflow/new`, and `ProjectLoader` puts the spec on the canvas once that
 * route is set up. The setup resets the provenance and the package scope, so a
 * file put on the canvas before it ran would lose both.
 *
 * Module state rather than navigation state: a spec can be megabytes, and the
 * browser keeps navigation state across a reload, which would open the file a
 * second time.
 */

type Listener = () => void;

// `any`, as `parseDataflowFile` hands it out: the shape check it passed is the
// one `useCode.loadTrill` needs, and no more.
let opened: { spec: any } | null = null;
let revision = 0;
const listeners = new Set<Listener>();

/** Open *spec* as a new dataflow: `ProjectLoader` loads it on `/dataflow/new`. */
export function openDataflowFile(spec: any): void {
    opened = { spec };
    revision += 1;
    for (const listener of listeners) listener();
}

/** Whether a picked file is waiting to be put on the canvas. */
export function hasOpenedDataflowFile(): boolean {
    return opened !== null;
}

/**
 * The picked file's spec, handed out once, or `null` when none is waiting.
 * Taking it clears it, so a later visit to `/dataflow/new` starts empty.
 */
export function takeOpenedDataflowFile(): any | null {
    const file = opened;
    opened = null;
    return file ? file.spec : null;
}

/**
 * Bumped by every {@link openDataflowFile}, for `useSyncExternalStore`: a file
 * picked while an unsaved dataflow is open changes no route, so the loader
 * needs this to notice it.
 */
export function openedDataflowFileRevision(): number {
    return revision;
}

export function subscribeOpenedDataflowFile(listener: Listener): () => void {
    listeners.add(listener);
    return () => {
        listeners.delete(listener);
    };
}

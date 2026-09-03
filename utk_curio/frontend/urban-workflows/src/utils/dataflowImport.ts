/**
 * Reading a dataflow file the user picked, and saying what went wrong.
 *
 * Split out of `UpMenu.handleFileUpload` (#238), which caught every failure
 * into `console.error` and left the canvas unchanged with no visible sign that
 * anything had happened. The parsing is pure so the failure messages can be
 * asserted without mounting UpMenu, which needs the whole provider stack.
 *
 * Three distinct failures reach the user, and telling them apart is the point:
 * the wrong kind of file, text that is not JSON at all, and JSON that parses
 * but is not a Curio dataflow. Reporting all three as "invalid JSON" sent
 * people looking for a syntax error in a perfectly well-formed file.
 */

export type DataflowParseResult =
    | { ok: true; spec: any }
    | { ok: false; message: string };

/**
 * Whether this file is worth trying to read as a dataflow.
 *
 * The extension is checked as well as the MIME type because the type is not
 * reliable: Windows reports an empty string for `.json` whenever no program is
 * registered for it, and some systems report `text/plain`. The old
 * `file.type === "application/json"` gate therefore refused valid dataflows on
 * exactly the platform the bug was reported from.
 */
export function looksLikeJsonFile(file: { name?: string; type?: string }): boolean {
    const name = (file?.name || "").toLowerCase();
    const type = (file?.type || "").toLowerCase();
    return name.endsWith(".json") || type === "application/json";
}

/** The message shown when the picked file is not a `.json` at all. */
export const NOT_JSON_FILE_MESSAGE =
    "Only .json dataflow files can be loaded. Pick a file saved from File > Save dataflow as.";

/** The message shown when a file could not be read off disk. */
export const UNREADABLE_FILE_MESSAGE =
    "That file could not be read. Check that it still exists and try again.";

/** The message shown when a dataflow parses but fails while being replayed. */
export function loadFailedMessage(err: unknown): string {
    const detail = err instanceof Error ? err.message : String(err ?? "");
    return detail
        ? `That dataflow could not be loaded: ${detail}`
        : "That dataflow could not be loaded.";
}

/**
 * Parse the text of a picked file into a dataflow spec.
 *
 * The shape check is deliberately the minimum `useCode.loadTrill` needs, an
 * array at `dataflow.nodes`, rather than a schema validation: `docs/schemas/
 * trill.v1.json` is enforced on the backend and running it here would refuse
 * older files the canvas still opens quite happily.
 */
export function parseDataflowFile(text: string): DataflowParseResult {
    let parsed: unknown;
    try {
        parsed = JSON.parse(text);
    } catch (err) {
        const detail = err instanceof Error ? err.message : String(err);
        return {
            ok: false,
            message: `That file is not valid JSON, so it could not be imported (${detail}).`,
        };
    }

    const spec = parsed as any;
    if (
        !spec ||
        typeof spec !== "object" ||
        Array.isArray(spec) ||
        !spec.dataflow ||
        typeof spec.dataflow !== "object" ||
        !Array.isArray(spec.dataflow.nodes)
    ) {
        return {
            ok: false,
            message:
                "That file is valid JSON but not a Curio dataflow: no dataflow.nodes list was found.",
        };
    }

    return { ok: true, spec };
}

/**
 * Bounded, truthful one-line summaries of a node's live runtime state.
 *
 * dev/111, ported to `imp/agentcatalog` by dev/129 at the owner's question
 * ("does this have to do with `nodeContext.current_input/current_output` still
 * sent empty?" — it did, and the fix had shipped only on `feat/agentscatalog`,
 * which is never merged back).
 *
 * Two rules the whole module exists to keep:
 *
 * - **The output's CONTENT is never forwarded.** An artifact id, a dataType and
 *   an error message are; the data itself is not, because a chat prompt is not
 *   a data channel.
 * - **Never-executed says so.** The vocabulary matches the server's own
 *   (`node_context.py`'s `runtimeStatus`), so the client and the runtime cannot
 *   describe the same node differently.
 *
 * The eval runner's twin, `evaluation/run_context.py`, writes these words for
 * the nodes of a dataflow none of which ran, and `test_skill_eval_context.py`
 * checks its words against this module's.
 */

export const NEVER_EXECUTED = "never-executed";

const ARTIFACT_CHARS = 60;
const ERROR_CHARS = 240;
const LISTED_SLOTS = 6;

/**
 * What `current_input` says of a node wired to others that has no input yet:
 * it waits for input, from these nodes, and whether each ran. Said as "no
 * upstream input", a chart wired to a loader that had not run read as a chart
 * nothing feeds, and an agent built it a new loader. "Waiting" holds for a
 * node with several inputs too, whose input stays empty until each one is in.
 */
const WIRED_INPUT = {
    waiting: "waiting for input",
    from: ": wired from ",
    node: "node ",
    between: "; ",
    more: "and {n} more",
    notRun: ", which has not run",
    failed: ", which failed",
    running: ", which is running",
    ran: ", which ran",
} as const;

type NodeData = {
    input?: unknown;
    output?: { code?: string; content?: unknown; outputType?: string; dataType?: string };
    in?: string;
    out?: string;
};

/** A node wired into another by a data edge, as `current_input` names it. */
export interface Feeder {
    id: string;
    /** Its type, as the dataflow's Trill writes it. */
    type?: string;
    /** Its live data, whose output says whether it ran. */
    data?: NodeData;
    /** The artifact the outputs store holds for it, if any. */
    storeOutput?: unknown;
}

type RunState = "error" | "running" | "ran" | "never";

/** Whether a node ran, as its output says: what `current_output` reads, and
 *  what `current_input` says of each node wired into one with no input yet. */
function runState(data: NodeData | undefined, storeOutput?: unknown): RunState {
    const code = typeof data?.output?.code === "string" ? data.output.code : "";
    if (code === "error") return "error";
    if (code === "exec") return "running";
    if (code === "success" || (storeOutput && typeof storeOutput === "object")) return "ran";
    return "never";
}

const FEEDER_RAN: Record<RunState, string> = {
    never: WIRED_INPUT.notRun,
    error: WIRED_INPUT.failed,
    running: WIRED_INPUT.running,
    ran: WIRED_INPUT.ran,
};

/** The nodes wired into a node, each with whether it ran, the first few by name. */
function namedFeeders(feeders: readonly Feeder[]): string {
    const named = feeders.slice(0, LISTED_SLOTS).map((feeder) =>
        `${WIRED_INPUT.node}${feeder.id}${feeder.type ? ` (${feeder.type})` : ""}` +
        FEEDER_RAN[runState(feeder.data, feeder.storeOutput)],
    );
    if (feeders.length > LISTED_SLOTS) {
        named.push(WIRED_INPUT.more.replace("{n}", String(feeders.length - LISTED_SLOTS)));
    }
    return named.join(WIRED_INPUT.between);
}

function truncate(text: string, max: number): string {
    return text.length > max ? text.slice(0, max) + "…" : text;
}

function declared(value: unknown): string {
    return typeof value === "string" && value.trim() ? ` (declared: ${value.trim()})` : "";
}

function artifactId(value: Record<string, unknown>): string {
    const id = value.dataset ?? value.path ?? "";
    return typeof id === "string" && id ? truncate(id, ARTIFACT_CHARS) : "";
}

/** One input value, whatever shape the propagation left it in. */
function summarizeValue(value: unknown): string {
    if (value === undefined || value === null || value === "") return "empty";
    if (typeof value === "string") return `string (${value.length} chars)`;
    if (typeof value === "number" || typeof value === "boolean") return typeof value;
    if (Array.isArray(value)) {
        const slots = value
            .slice(0, LISTED_SLOTS)
            .map((slot, i) => `[${i}] ${slot === undefined || slot === null ? "empty" : summarizeValue(slot)}`);
        return `MULTIPLE (${value.length} slots): ${slots.join("; ")}`;
    }
    if (typeof value === "object") {
        const record = value as Record<string, unknown>;
        const type = typeof record.dataType === "string" && record.dataType
            ? record.dataType
            : "unknown type";
        const id = artifactId(record);
        return id ? `${type} from artifact ${id}` : type;
    }
    return "input present (unrecognized shape)";
}

/**
 * `current_input`: what this node received when it last ran. With none, the
 * nodes wired into it by data edges (*feeders*) say whether it waits for input
 * from them or nothing feeds it.
 */
export function summarizeNodeInput(data: NodeData | undefined, feeders: readonly Feeder[] = []): string {
    if (!data) return "";
    const value = data.input;
    if (value === undefined || value === null || value === "") {
        if (feeders.length > 0) {
            return `${WIRED_INPUT.waiting}${declared(data.in)}${WIRED_INPUT.from}${namedFeeders(feeders)}`;
        }
        return `no upstream input${declared(data.in)}`;
    }
    return `${summarizeValue(value)}${declared(data.in)}`;
}

/** `current_output`: what this node produced, or why it did not. */
export function summarizeNodeOutput(
    data: NodeData | undefined,
    storeOutput?: unknown,
): string {
    if (!data) return "";
    const output = data.output ?? {};
    const code = typeof output.code === "string" ? output.code : "";
    const suffix = declared(data.out);
    const state = runState(data, storeOutput);
    if (state === "error") {
        // The one `content` that IS forwarded: short, runtime-authored, and
        // exactly what an agent asked "why is this node red?" needs.
        return `error: ${truncate(String(output.content ?? "unknown error"), ERROR_CHARS)}${suffix}`;
    }
    if (state === "running") return `running${suffix}`;
    if (state === "never") return `${NEVER_EXECUTED}${suffix}`;
    // It ran: here, or in a run the outputs store kept.
    const store = storeOutput && typeof storeOutput === "object"
        ? (storeOutput as Record<string, unknown>)
        : {};
    if (code === "success") {
        const type = output.dataType || output.outputType || (
            typeof store.dataType === "string" ? store.dataType : ""
        ) || "unknown type";
        const id = artifactId(store);
        return `success: ${type}${id ? ` artifact ${id}` : ""}${suffix}`;
    }
    const type = typeof store.dataType === "string" && store.dataType ? store.dataType : "unknown type";
    const id = artifactId(store);
    return `success (restored): ${type}${id ? ` artifact ${id}` : ""}${suffix}`;
}

/** The artifact the outputs store holds for a node, if any. */
export function storeOutputFor(
    outputs: Array<{ nodeId?: string; output?: unknown }> | undefined,
    nodeId: string,
): unknown {
    if (!Array.isArray(outputs)) return undefined;
    return outputs.find((entry) => entry?.nodeId === nodeId)?.output;
}

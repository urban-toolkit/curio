import { nodeRunStatus } from "../../utils/nodeRunStatus";

/**
 * The node header renders "Done" / a spinner / "Error" from these same
 * ``output.code`` values, and every run assertion in the e2e suite used to match
 * that copy with a ``^(Done|Error)$`` regex. ``data-curio-node-status`` replaces
 * it, so the mapping has to stay exactly aligned with what the header shows.
 */

const out = (code: string) => ({ code, content: "" }) as any;

describe("nodeRunStatus", () => {
    test("maps the three codes the header renders", () => {
        expect(nodeRunStatus(out("success"))).toBe("done");
        expect(nodeRunStatus(out("exec"))).toBe("running");
        expect(nodeRunStatus(out("error"))).toBe("error");
    });

    test("a node that has never run is idle, not missing", () => {
        // The attribute is always present so a waiter can poll it without
        // having to distinguish "no attribute" from "not started".
        expect(nodeRunStatus(undefined)).toBe("idle");
    });

    test("an unmodelled code falls back to idle rather than leaking through", () => {
        expect(nodeRunStatus(out(""))).toBe("idle");
        expect(nodeRunStatus(out("something-new"))).toBe("idle");
    });
});

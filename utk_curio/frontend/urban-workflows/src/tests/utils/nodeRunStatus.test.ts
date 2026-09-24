import { nodeRunStatus, nodeRunError } from "../../utils/nodeRunStatus";

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

describe("nodeRunError (#318)", () => {
    const err = (content: unknown) => ({ code: "error", content }) as any;

    test("carries the message of a failed node", () => {
        expect(nodeRunError(err("Binder Error: no such column"))).toBe(
            "Binder Error: no such column",
        );
    });

    test("says nothing for a node that did not fail", () => {
        expect(nodeRunError(out("success"))).toBeUndefined();
        expect(nodeRunError(out("exec"))).toBeUndefined();
        expect(nodeRunError(undefined)).toBeUndefined();
    });

    test("an empty message is absent rather than an empty attribute", () => {
        // `read_node_error_text` falls back to the output box when this is
        // missing; an empty string would end that search with nothing.
        expect(nodeRunError(err(""))).toBeUndefined();
        expect(nodeRunError(err("   "))).toBeUndefined();
    });

    test("a very long message is truncated, so the DOM stays bounded", () => {
        const long = "x".repeat(5000);
        const text = nodeRunError(err(long))!;
        expect(text.length).toBeLessThan(2100);
        expect(text.endsWith("…")).toBe(true);
    });
});

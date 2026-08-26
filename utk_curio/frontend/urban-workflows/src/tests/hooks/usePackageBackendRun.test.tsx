/**
 * dev/91 commit 5 — usePackageBackendRun: the sandbox runner exists exactly
 * for backendHandler descriptors, posts the documented payload shape
 * ({content, input}), and maps success/handler-error/transport-error onto
 * the node's output surfaces — never a silent failure.
 */
import React from "react";
import { render } from "@testing-library/react";

jest.mock("../../api/packageBackendApi", () => ({
    invokePackageBackend: jest.fn(),
}));

import { invokePackageBackend } from "../../api/packageBackendApi";
import { registerNode, clearPackageNodes } from "../../registry/nodeRegistry";
import { usePackageBackendRun, PackageBackendRun } from "../../hook/usePackageBackendRun";
import type { NodeDescriptor } from "../../registry/types";

const mockInvoke = invokePackageBackend as jest.MockedFunction<typeof invokePackageBackend>;

const DESCRIPTOR = {
    id: "ai.agent.wordcount/word-count-kind@1",
    source: "package",
    package: { packageId: "ai.agent.wordcount", major: 1, version: "1.0.0" },
    category: "computation",
    label: "Word count",
    icon: {} as never,
    inputPorts: [],
    outputPorts: [],
    editor: "none",
    inPalette: true,
    description: "",
    hasCode: false,
    hasWidgets: false,
    hasGrammar: false,
    backendHandler: "word-count",
    adapter: {
        handles: [],
        editor: null,
        container: {},
        inputIconType: null,
        outputIconType: null,
        useNodeBehavior: () => ({}),
    },
} as unknown as NodeDescriptor;

function Probe({ nodeType, onRun }: { nodeType: string; onRun: (r: PackageBackendRun | null) => void }) {
    onRun(usePackageBackendRun(nodeType));
    return null;
}

function resolveRun(nodeType: string): PackageBackendRun | null {
    let captured: PackageBackendRun | null = null;
    render(<Probe nodeType={nodeType} onRun={(r) => { captured = r; }} />);
    return captured;
}

describe("usePackageBackendRun (dev/91)", () => {
    beforeEach(() => {
        mockInvoke.mockReset();
        registerNode(DESCRIPTOR);
    });
    afterEach(() => clearPackageNodes());

    it("is null for templates without a backendHandler", () => {
        expect(resolveRun("curio.builtin/unknown-kind@1")).toBeNull();
    });

    it("posts the documented payload shape and maps a success reply", async () => {
        mockInvoke.mockResolvedValue({
            reply: { contract: "curio.pkgbackend.v1", ok: true, result: { words: 3 } },
            invocationId: "i1", durationMs: 5, limitsApplied: [], entryDigest: "d",
        });
        const run = resolveRun(DESCRIPTOR.id as string);
        expect(run).not.toBeNull();
        const outcome = await run!({ content: "note text", input: { rows: 1 } });
        expect(mockInvoke).toHaveBeenCalledWith(
            "ai.agent.wordcount@1", "word-count",
            { content: "note text", input: { rows: 1 } },
        );
        expect(outcome.ok).toBe(true);
        expect(outcome.content).toContain('"words": 3');
    });

    it("a well-formed handler-error reply surfaces its kind and text", async () => {
        mockInvoke.mockResolvedValue({
            reply: { contract: "curio.pkgbackend.v1", ok: false,
                     error: "the handler exploded", kind: "handler-error" },
            invocationId: "i2", durationMs: 5, limitsApplied: [], entryDigest: "d",
        });
        const outcome = await resolveRun(DESCRIPTOR.id as string)!({});
        expect(outcome).toEqual({ ok: false, content: "handler-error: the handler exploded" });
    });

    it("a transport failure (409 drift, 503 busy, …) surfaces the message", async () => {
        mockInvoke.mockRejectedValue(new Error(
            "the backend entry changed on disk since install (digest mismatch) — reinstall the package before invoking it",
        ));
        const outcome = await resolveRun(DESCRIPTOR.id as string)!({});
        expect(outcome.ok).toBe(false);
        expect(outcome.content).toContain("reinstall the package");
    });
});

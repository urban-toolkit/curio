/**
 * The agent import picker's cases. catalogActionScope.test.tsx runs them, and
 * agentImportPickerColdLoad.test.tsx runs them again behind a module that
 * loads slowly. A test file that runs them mocks `services/agents/agentsApi`.
 */
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

/** *clockMs* is each case's clock; Jest's own 5 s when left out. */
export function describeTheAgentImportPicker(clockMs?: number): void {
  describe("the agent import picker can assemble a real package", () => {
    test("a second selection adds to the first instead of replacing it", async () => {
      // An agent package is `<id>@<major>/manifest.json` plus
      // `<id>@<major>/prompts/*.md` - two directories - and one OS file dialog
      // cannot span two directories. `pick` used to `setFiles(read)`, so the
      // second dialog discarded the manifest picked in the first and the flow
      // could never be completed against the documented layout.
      const { AgentImportModal } = await import(
        "../../components/agents/catalog/AgentImportModal"
      );
      render(<AgentImportModal onClose={() => {}} onImported={() => {}} />);
      const input = screen.getByLabelText("Package files") as HTMLInputElement;
      // Read the running tally, not the page: the hint above the picker also
      // says "manifest.json", so a text query matches two nodes.
      const summary = () => document.querySelector(".summary")?.textContent ?? "";

      const manifest = new File(['{"id":"a"}'], "manifest.json", { type: "application/json" });
      await userEvent.upload(input, manifest);
      await waitFor(() => expect(summary()).toContain("manifest.json"));
      expect(summary()).toContain("0 prompt file");

      const prompt = new File(["hello"], "explain.txt", { type: "text/plain" });
      await userEvent.upload(input, prompt);
      await waitFor(() => expect(summary()).toContain("1 prompt file"));
      // The manifest survived the second dialog. This is the whole point.
      expect(summary()).toContain("manifest.json");
    }, clockMs);

    test("Clear empties an accumulating selection", async () => {
      const { AgentImportModal } = await import(
        "../../components/agents/catalog/AgentImportModal"
      );
      render(<AgentImportModal onClose={() => {}} onImported={() => {}} />);
      const input = screen.getByLabelText("Package files") as HTMLInputElement;
      await userEvent.upload(
        input,
        new File(['{"id":"a"}'], "manifest.json", { type: "application/json" }),
      );
      await userEvent.click(await screen.findByRole("button", { name: "Clear" }));
      // The whole tally goes, not just its text.
      await waitFor(() => expect(document.querySelector(".summary")).toBeNull());
    }, clockMs);
  });
}

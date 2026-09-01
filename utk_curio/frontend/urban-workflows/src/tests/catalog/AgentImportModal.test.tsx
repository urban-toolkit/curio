import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

jest.mock("../../api/agentsApi", () => ({
  agentsApi: { uploadImport: jest.fn() },
}));

import { agentsApi } from "../../api/agentsApi";
import { AgentImportModal } from "../../components/agents/catalog/AgentImportModal";
import { buildUploadPayload } from "../../components/agents/catalog/buildUploadPayload";

const api = agentsApi as jest.Mocked<typeof agentsApi>;

const MANIFEST = { id: "agent.my-agent", version: "1.0.0" };

describe("buildUploadPayload", () => {
  it("assembles manifest + prompts/<name> entries", () => {
    const out = buildUploadPayload([
      { name: "manifest.json", text: JSON.stringify(MANIFEST) },
      { name: "instruction.txt", text: "do the thing" },
    ]);
    expect(out.manifest).toEqual(MANIFEST);
    expect(out.prompts).toEqual({ "prompts/instruction.txt": "do the thing" });
  });

  it("requires exactly one manifest and only .txt prompts", () => {
    expect(() => buildUploadPayload([{ name: "instruction.txt", text: "x" }])).toThrow(
      /exactly one manifest/i,
    );
    expect(() =>
      buildUploadPayload([
        { name: "manifest.json", text: "{}" },
        { name: "manifest.json", text: "{}" },
      ]),
    ).toThrow(/exactly one manifest/i);
    expect(() =>
      buildUploadPayload([
        { name: "manifest.json", text: "{}" },
        { name: "evil.zip", text: "x" },
      ]),
    ).toThrow(/unsupported file/i);
    expect(() => buildUploadPayload([{ name: "manifest.json", text: "{not json" }])).toThrow(
      /not valid JSON/i,
    );
  });
});

describe("AgentImportModal", () => {
  function pickFiles(...files: File[]) {
    const input = screen.getByLabelText("Package files");
    fireEvent.change(input, { target: { files } });
  }

  it("uploads the assembled payload and reports the new dirName", async () => {
    api.uploadImport.mockResolvedValue({ dirName: "agent.my-agent@1.0.0" } as any);
    const onImported = jest.fn();
    render(<AgentImportModal onImported={onImported} onClose={jest.fn()} />);
    expect(screen.getByRole("button", { name: "Import" })).toBeDisabled(); // no manifest yet
    pickFiles(
      new File([JSON.stringify(MANIFEST)], "manifest.json", { type: "application/json" }),
      new File(["do the thing"], "instruction.txt", { type: "text/plain" }),
    );
    await waitFor(() =>
      expect(screen.getByText(/manifest\.json · 1 prompt file/)).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Import" }));
    await waitFor(() =>
      expect(api.uploadImport).toHaveBeenCalledWith(MANIFEST, {
        "prompts/instruction.txt": "do the thing",
      }),
    );
    expect(onImported).toHaveBeenCalledWith("agent.my-agent@1.0.0");
  });

  it("shows the server's field-specific error verbatim", async () => {
    api.uploadImport.mockRejectedValue(
      Object.assign(new Error("'agent.x@1.0.0' already exists in your store — definitions are immutable; bump the version"), {
        status: 409,
      }),
    );
    render(<AgentImportModal onImported={jest.fn()} onClose={jest.fn()} />);
    pickFiles(new File([JSON.stringify(MANIFEST)], "manifest.json"));
    await waitFor(() => expect(screen.getByText(/0 prompt files/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Import" }));
    await waitFor(() =>
      expect(screen.getByText(/definitions are immutable; bump the version/)).toBeInTheDocument(),
    );
  });
});

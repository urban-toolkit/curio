import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom";

/**
 * Import skill: what was picked is reviewed before anything is kept.
 *
 * The review is the server's reading of the upload (`skillsApi.checkImport`):
 * the skill's name and description, what does not follow the format, its
 * files, and why it cannot be kept, if it cannot. Every agent offered starts
 * picked, and Import gives the skill to those left picked. A name another
 * skill takes gets a name to edit, which is checked again before Import.
 */

const mockCheck = jest.fn();
const mockImport = jest.fn();
jest.mock("../../services/agents/skillsApi", () => ({
  skillsApi: {
    checkImport: (...args: unknown[]) => mockCheck(...args),
    importSkill: (...args: unknown[]) => mockImport(...args),
  },
}));

import { SkillImportModal } from "../../components/agents/catalog/SkillImportModal";

const FINDER = { id: "agent.curio.dataset-finder", coord: "agent.curio.dataset-finder@1", name: "Dataset Finder" };
const RESEARCHER = { id: "agent.curio.researcher", coord: "agent.curio.researcher@1", name: "Researcher" };
const REVIEW = {
  name: "street-trees",
  givenName: "street-trees",
  description: "Use this skill when a dataflow counts street trees.",
  warnings: ["it holds author, which the format does not define"],
  leftOut: [],
  files: ["references/species.md"],
  problem: null,
  rename: false,
  replaces: false,
  agents: [FINDER, RESEARCHER],
};

function pickFiles() {
  const file = new File(["---\nname: street-trees\n---\n"], "SKILL.md");
  fireEvent.change(screen.getByLabelText("Skill files"), { target: { files: [file] } });
}

const importButton = () => screen.getByRole("button", { name: /^(Import|Importing…|Replace)$/ });

beforeEach(() => {
  mockCheck.mockReset();
  mockImport.mockReset();
});

describe("SkillImportModal", () => {
  it("reviews what was picked, with every agent offered picked, and gives the skill to those left picked", async () => {
    mockCheck.mockResolvedValueOnce(REVIEW);
    mockImport.mockResolvedValueOnce({ skill: { name: "street-trees" }, agents: ["Dataset Finder"], replaced: false });
    const onImported = jest.fn();
    render(<SkillImportModal onImported={onImported} onClose={jest.fn()} />);
    expect(importButton()).toBeDisabled();
    pickFiles();

    const review = await waitFor(() => {
      const found = document.querySelector('[data-curio-skill-review="true"]');
      expect(found).not.toBeNull();
      return found as HTMLElement;
    });
    expect(mockCheck).toHaveBeenCalledWith([expect.objectContaining({ path: "SKILL.md" })], undefined);
    expect(within(review).getByText(REVIEW.description)).toBeInTheDocument();
    expect(within(review).getByText(REVIEW.warnings[0])).toBeInTheDocument();
    expect(within(review).getByText("references/species.md")).toBeInTheDocument();
    expect(within(review).getAllByRole("checkbox").map((box) => (box as HTMLInputElement).checked)).toEqual([
      true, true,
    ]);

    fireEvent.click(within(review).getByLabelText("Researcher"));
    fireEvent.click(importButton());
    await waitFor(() => expect(onImported).toHaveBeenCalledWith("street-trees"));
    expect(mockImport).toHaveBeenCalledTimes(1);
    const [files, fields] = mockImport.mock.calls[0];
    expect(files.map((file: { path: string }) => file.path)).toEqual(["SKILL.md"]);
    expect(fields).toEqual({ name: "street-trees", agents: [FINDER.coord] });
  });

  it("offers a name for a skill whose name is taken, and imports once that name is checked", async () => {
    mockCheck
      .mockResolvedValueOnce({
        ...REVIEW, name: "widgets", givenName: "widgets", problem: "Curio ships a skill named widgets", rename: true,
      })
      .mockResolvedValueOnce({ ...REVIEW, name: "widgets-2", givenName: "widgets" });
    mockImport.mockResolvedValueOnce({ skill: { name: "widgets-2" }, agents: [], replaced: false });
    const onImported = jest.fn();
    render(<SkillImportModal onImported={onImported} onClose={jest.fn()} />);
    pickFiles();

    expect(await screen.findByText("Curio ships a skill named widgets")).toBeInTheDocument();
    const name = screen.getByLabelText("Skill name");
    expect(name).toHaveValue("widgets-2");
    expect(importButton()).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Check name" }));
    await waitFor(() => expect(mockCheck).toHaveBeenLastCalledWith(expect.any(Array), "widgets-2"));
    await waitFor(() => expect(importButton()).toBeEnabled());
    expect(screen.queryByText("Curio ships a skill named widgets")).toBeNull();

    fireEvent.click(importButton());
    await waitFor(() => expect(onImported).toHaveBeenCalledWith("widgets-2"));
    expect(mockImport.mock.calls[0][1]).toEqual({ name: "widgets-2", agents: [FINDER.coord, RESEARCHER.coord] });
  });

  it("names a newer version that replaces the account's own skill", async () => {
    mockCheck.mockResolvedValueOnce({ ...REVIEW, replaces: true });
    render(<SkillImportModal onImported={jest.fn()} onClose={jest.fn()} />);
    pickFiles();
    expect(await screen.findByText("It replaces your skill street-trees, an older version.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Replace" })).toBeEnabled();
  });

  it("says why an upload cannot be read, and keeps Import off", async () => {
    mockCheck.mockRejectedValueOnce(new Error("the upload holds no SKILL.md"));
    render(<SkillImportModal onImported={jest.fn()} onClose={jest.fn()} />);
    pickFiles();
    expect(await screen.findByRole("alert")).toHaveTextContent("the upload holds no SKILL.md");
    expect(importButton()).toBeDisabled();
    expect(mockImport).not.toHaveBeenCalled();
  });

  it("keeps Import off when the review says the skill cannot be kept under any name", async () => {
    mockCheck.mockResolvedValueOnce({
      ...REVIEW, problem: "its description is 1,039 characters, more than 1,024", rename: false,
    });
    render(<SkillImportModal onImported={jest.fn()} onClose={jest.fn()} />);
    pickFiles();
    expect(await screen.findByText("its description is 1,039 characters, more than 1,024")).toBeInTheDocument();
    expect(screen.queryByLabelText("Skill name")).toBeNull();
    expect(importButton()).toBeDisabled();
  });
});

/**
 * The category chips under the canvas title and in "Edit categories".
 */
import React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import DataflowCategoryInput from "../../components/projects/DataflowCategoryInput";
import { TrillGenerator } from "../../TrillGenerator";

const CATEGORIES = {
  source: "example" as const,
  auto: { tags: ["Autark"], data_type: ["Geometries"] },
};

describe("DataflowCategoryInput", () => {
  test("automatic chips cannot be removed; hand-set ones can", () => {
    const onChange = jest.fn();
    render(
      <DataflowCategoryInput categories={CATEGORIES} hand={{ topic: ["Greenery"] }} onChange={onChange} />,
    );

    expect(screen.getByText("Examples")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Remove Autark" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Remove Geometries" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Remove Greenery" }));
    expect(onChange).toHaveBeenCalledWith({});
  });

  test("+ Category adds to the chosen section, and a new complexity replaces the old", async () => {
    const onChange = jest.fn();
    const onOpenAdd = jest.fn();
    render(
      <DataflowCategoryInput
        hand={{ complexity: ["Beginner"] }}
        onChange={onChange}
        onOpenAdd={onOpenAdd}
      />,
    );

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "+ Category" }));
    });
    expect(onOpenAdd).toHaveBeenCalled();
    fireEvent.change(screen.getByRole("combobox", { name: "Category section" }), {
      target: { value: "complexity" },
    });
    // A field with a suggestion list is a combobox.
    fireEvent.change(screen.getByRole("combobox", { name: "Category name" }), {
      target: { value: "Advanced" },
    });
    fireEvent.keyDown(screen.getByRole("combobox", { name: "Category name" }), { key: "Enter" });

    expect(onChange).toHaveBeenCalledWith({ complexity: ["Advanced"] });
  });

  test("read-only offers neither remove nor add", () => {
    render(<DataflowCategoryInput hand={{ city: ["Milan"] }} />);

    expect(screen.getByText("Milan")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Remove Milan" })).toBeNull();
    expect(screen.queryByRole("button", { name: "+ Category" })).toBeNull();
  });

  test("past maxVisible the rest fold into +N", () => {
    render(
      <DataflowCategoryInput
        categories={{ auto: { tags: ["A", "B", "C"], data_type: ["D"] } }}
        hand={{}}
        maxVisible={2}
      />,
    );

    expect(screen.queryByText("C")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Show 2 more categories" }));
    expect(screen.getByText("C")).toBeTruthy();
  });
});

describe("TrillGenerator categories", () => {
  test("a save writes them, even empty; other callers leave the key out", () => {
    const saved = TrillGenerator.generateTrill([], [], "Mine", "", [], "", [], { city: ["Milan"] });
    expect(saved.dataflow.categories).toEqual({ city: ["Milan"] });
    expect(TrillGenerator.generateTrill([], [], "Mine", "", [], "", [], {}).dataflow.categories).toEqual({});
    expect("categories" in TrillGenerator.generateTrill([], [], "Mine").dataflow).toBe(false);
  });
});

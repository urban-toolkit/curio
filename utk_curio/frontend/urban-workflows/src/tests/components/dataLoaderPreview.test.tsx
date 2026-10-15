/**
 * The Data Loading preview and its folded chip
 * (plans/data-loading-expressive-preview-memo.md, sections 3.3 and 5).
 */
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { DataLoaderPreview, loaderAccessibleName, loaderTitle } from "../../components/nodes/DataLoaderPreview";
import { DataLoaderChip } from "../../components/nodes/DataLoaderGlyph";
import { detectLoaderProfile } from "../../services/datasetCatalog/loaderProfile";

const catalog = detectLoaderProfile('gdf = curio_load_data("data.utk.chicago-community-areas")\nreturn gdf', {
  lookupDataset: () => ({ title: "Chicago community areas", format: "geojson" }),
});

describe("the preview", () => {
  it("names the type, the dataset and where it comes from", () => {
    render(<DataLoaderPreview profile={catalog} />);
    const group = screen.getByRole("group", {
      name: "Loads GeoJSON from the Data Catalog: Chicago community areas",
    });
    expect(group.getAttribute("data-data-type")).toBe("geojson");
    expect(group.getAttribute("data-source-kind")).toBe("catalog");
    expect(screen.getByText("GeoJSON")).toBeTruthy();
    expect(screen.getByText("Chicago community areas")).toBeTruthy();
    expect(screen.getByText("Data Catalog")).toBeTruthy();
    expect(screen.getByText("Not run yet")).toBeTruthy();
  });

  it("opens the dataset's details from its address", () => {
    const open = jest.fn();
    render(<DataLoaderPreview profile={catalog} onOpenDataset={open} />);
    fireEvent.click(screen.getByRole("button", { name: "data.utk.chicago-community-areas" }));
    expect(open).toHaveBeenCalledWith("data.utk.chicago-community-areas");
  });

  it("names a file by its file name and an API by its host", () => {
    const file = detectLoaderProfile('df = pd.read_csv("/data/chicago/taxi_trips_2024.csv")');
    const { unmount } = render(<DataLoaderPreview profile={file} />);
    expect(screen.getByText("taxi_trips_2024.csv")).toBeTruthy();
    expect(screen.getByTitle("/data/chicago/taxi_trips_2024.csv")).toBeTruthy();
    unmount();
    const api = detectLoaderProfile('r = requests.get("https://data.cityofchicago.org/resource/x.json?key=SECRET")');
    const { container } = render(<DataLoaderPreview profile={api} />);
    expect(container.textContent).toContain("data.cityofchicago.org");
    expect(container.textContent).not.toContain("SECRET");
  });

  it("says what it is doing about a type it does not know", () => {
    const silent = detectLoaderProfile("x = build()\nreturn x");
    const { rerender } = render(<DataLoaderPreview profile={silent} detecting />);
    expect(screen.getByText("Detecting type…")).toBeTruthy();
    expect(screen.getByText("Checking the returned data once")).toBeTruthy();
    rerender(<DataLoaderPreview profile={silent} />);
    expect(screen.getByText("Data")).toBeTruthy();
    expect(screen.getByText("Run to see the type")).toBeTruthy();
  });

  it("shows the run's state", () => {
    const { rerender } = render(<DataLoaderPreview profile={catalog} outputCode="exec" />);
    expect(screen.getByText("Running…")).toBeTruthy();
    rerender(<DataLoaderPreview profile={catalog} outputCode="success" />);
    expect(screen.getByText("Loaded")).toBeTruthy();
    rerender(<DataLoaderPreview profile={catalog} outputCode="error" />);
    expect(screen.getByText(/last run failed/)).toBeTruthy();
  });

  it("points to a code change waiting for review", () => {
    const show = jest.fn();
    render(<DataLoaderPreview profile={catalog} pendingProposal onShowCode={show} />);
    fireEvent.click(screen.getByRole("button", { name: "Show code" }));
    expect(show).toHaveBeenCalled();
  });

  it("starts every line with the same glyph slot, so the text lines up with or without a glyph", () => {
    const silent = detectLoaderProfile("x = build()\nreturn x");
    for (const props of [{ profile: catalog }, { profile: catalog, outputCode: "success" }, { profile: silent }, { profile: silent, detecting: true }]) {
      const { container, unmount } = render(<DataLoaderPreview {...(props as any)} />);
      const facts = container.querySelector('[data-testid="data-loader-preview"]')!.lastElementChild!;
      for (const line of Array.from(facts.children)) {
        expect(line.firstElementChild?.className).toContain("lineIcon");
      }
      unmount();
    }
  });

  it("never draws the play glyph, which is the header's Play button alone", () => {
    // The e2e suite finds a node's Play by svg.fa-circle-play; a second one in
    // the body would read as a button that does nothing.
    const silent = detectLoaderProfile("x = build()\nreturn x");
    for (const props of [{ profile: catalog }, { profile: silent }, { profile: catalog, outputCode: "success" }]) {
      const { container, unmount } = render(<DataLoaderPreview {...(props as any)} />);
      expect(container.querySelector('svg[data-icon="circle-play"]')).toBeNull();
      expect(container.querySelector('svg[data-icon="clock"]') !== null || props.outputCode === "success").toBe(true);
      unmount();
    }
  });

  it("titles every kind of source", () => {
    expect(loaderTitle({ kind: "disk", address: "" })).toBe("File (path built in code)");
    expect(loaderTitle({ kind: "api", address: "" })).toBe("API (address built in code)");
    expect(loaderTitle({ kind: "inline", address: "" })).toBe("Defined in code");
    expect(loaderTitle(undefined)).toBe("Custom loader");
    expect(loaderAccessibleName(detectLoaderProfile("df = pd.DataFrame({'a': [1]})"))).toBe(
      "Loads Table from data defined in its code",
    );
  });
});

describe("the folded chip", () => {
  it("draws the arrow, the typed database and the type's label", () => {
    render(<DataLoaderChip dataType="geotiff" />);
    const chip = screen.getByTestId("data-loader-chip");
    expect(chip.textContent).toContain("Raster");
    expect(screen.getByTestId("data-loader-glyph").getAttribute("data-data-type")).toBe("geotiff");
  });

  it("says Data for an unknown type and … while detecting", () => {
    const { rerender } = render(<DataLoaderChip dataType="unknown" />);
    expect(screen.getByTestId("data-loader-chip").textContent).toBe("Data");
    rerender(<DataLoaderChip dataType="unknown" detecting />);
    expect(screen.getByTestId("data-loader-chip").textContent).toBe("…");
  });
});

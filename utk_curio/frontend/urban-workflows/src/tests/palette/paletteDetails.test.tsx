import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";

/**
 * Every palette row offers a way into its item's details.
 *
 * A catalog card always offers "View details"; the same dataset, agent or
 * package in the Tools palette offered nothing, so the canvas, where people
 * actually work, was the one place its details could not be read. Each row now
 * carries a details button, and it opens the same modal the catalog does.
 */

jest.mock("reactflow", () => ({
  useReactFlow: () => ({ getNodes: () => [], setNodes: jest.fn(), setCenter: jest.fn() }),
}));
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));
jest.mock("../../components/menus/nodes/toolsMenuPackagePalette", () => ({
  OVERLAY_TRIGGER_DELAY_PROPS: { show: 0, hide: 0 },
}));
jest.mock("../../components/datasets/catalog/DatasetConnectionBadge", () => ({
  DatasetConnectionBadge: () => null,
}));
jest.mock("../../api/agentsApi", () => ({
  agentsApi: { readDefinition: jest.fn(() => new Promise(() => {})) },
}));
jest.mock("../../api/packagesApi", () => ({
  packagesApi: {
    listInstalled: jest.fn(),
    catalog: jest.fn(),
    getDefaults: jest.fn(() => new Promise(() => {})),
    download: jest.fn(),
  },
}));
jest.mock("../../components/packages/editing", () => ({
  PackageMetadataModal: () => null,
}));
jest.mock("../../components/packages/CatalogPublishPill", () => ({
  CatalogPublishPill: () => null,
}));
jest.mock("../../components/menus/nodes/toolsMenuPackagePalette/PackagePaletteRows", () => ({
  PackageTemplateRow: () => null,
}));

import { DetailsButton } from "../../components/DetailsButton";
import { DatasetRow } from "../../components/menus/nodes/datasetPalette/DatasetPaletteRows";
import { AgentPaletteRow } from "../../components/menus/nodes/agentsPalette/AgentPaletteRow";
import { InstalledPackageAccordion } from "../../components/menus/nodes/toolsMenuPackagePalette/InstalledPackageAccordion";
import { DatasetDetailsContext } from "../../components/datasets/catalog/datasetDetailsContext";
import type { DatasetCatalogItem } from "../../services/datasetCatalog";

// eslint-disable-next-line @typescript-eslint/no-var-requires
const { packagesApi } = require("../../api/packagesApi") as {
  packagesApi: { listInstalled: jest.Mock; catalog: jest.Mock };
};

describe("DetailsButton", () => {
  test("opens details without also clicking the row it sits in", () => {
    const onRow = jest.fn();
    const onClick = jest.fn();
    render(
      <div onClick={onRow}>
        <DetailsButton label="View Bike Routes details" onClick={onClick} />
      </div>,
    );
    fireEvent.click(screen.getByRole("button", { name: "View Bike Routes details" }));
    expect(onClick).toHaveBeenCalledTimes(1);
    expect(onRow).not.toHaveBeenCalled();
  });
});

describe("a dataset palette row", () => {
  test("opens the dataset's details through the canvas's one modal", () => {
    const openDatasetDetails = jest.fn();
    const dataset = {
      id: "imported.bikes",
      title: "Bike Routes",
      origin: "imported",
      format: "csv",
      uri: "curio://datasets/imported.bikes",
      consumerNodeIds: [],
      updatedAt: "2026-07-14T00:00:00Z",
      tags: [],
      installed: true,
    } as DatasetCatalogItem;
    render(
      <DatasetDetailsContext.Provider value={{ openDatasetDetails }}>
        <DatasetRow dataset={dataset} />
      </DatasetDetailsContext.Provider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "View Bike Routes details" }));
    expect(openDatasetDetails).toHaveBeenCalledWith("imported.bikes", { fallbackDataset: dataset });
  });

  test("lets its id wrap after each dot and before the version (#527)", () => {
    // One unbreakable line cut "data.projectsidewalk.chicago-labels@1" to
    // "data.projectsidewalk.chicago-lab...", so the version never showed.
    const dataset = {
      id: "data.projectsidewalk.chicago-labels",
      title: "Project Sidewalk Chicago Labels",
      origin: "hub",
      format: "csv",
      dirName: "data.projectsidewalk.chicago-labels@1",
      uri: "curio://datasets/data.projectsidewalk.chicago-labels",
      consumerNodeIds: [],
      updatedAt: "2026-07-14T00:00:00Z",
      tags: [],
      installed: true,
    } as DatasetCatalogItem;
    render(
      <DatasetDetailsContext.Provider value={{ openDatasetDetails: jest.fn() }}>
        <DatasetRow dataset={dataset} />
      </DatasetDetailsContext.Provider>,
    );
    const id = screen.getByText("data.projectsidewalk.chicago-labels@1");
    expect(id.innerHTML).toBe(
      "data.<wbr>projectsidewalk.<wbr>chicago-labels<wbr>@1",
    );
    // The title is its own element, not the id's line.
    expect(screen.getByText("Project Sidewalk Chicago Labels")).not.toBe(id);
  });
});

describe("the dataset palette row's text (#527)", () => {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const fs = require("fs") as typeof import("fs");
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const path = require("path") as typeof import("path");
  const css = fs.readFileSync(
    path.resolve(__dirname, "../../components/menus/nodes/datasetPalette/DatasetPaletteRows.module.css"),
    "utf8",
  );
  const rule = (selector: string) => {
    const at = css.indexOf("\n" + selector + " {");
    if (at === -1) return "";
    const open = css.indexOf("{", at);
    return css.slice(open + 1, css.indexOf("}", open));
  };

  test("gives the title two lines instead of one", () => {
    const title = rule(".datasetRowTitle");
    expect(title).toMatch(/-webkit-line-clamp:\s*2;/);
    expect(title).not.toMatch(/white-space:\s*nowrap/);
  });

  test("lets the id wrap", () => {
    expect(rule(".datasetRowId")).not.toMatch(/white-space:\s*nowrap/);
    expect(rule(".datasetRowId")).toMatch(/overflow-wrap:\s*anywhere;/);
  });
});

describe("an agent palette row", () => {
  test("opens the agent's details, not the whole catalog drawer", () => {
    const onOpen = jest.fn();
    const agent: any = {
      id: "agent.chat-agent",
      version: "1.0.0",
      dirName: "agent.chat-agent@1.0.0",
      name: "Chat",
      category: "node",
      purpose: "assistant for a node or the canvas",
      capabilities: [],
      hooks: ["node"],
      provenance: { publisher: "curio", trust: "built-in" },
      imported: true,
      published: false,
      requiresAgents: [],
    };
    render(<AgentPaletteRow agent={agent} onOpen={onOpen} />);
    fireEvent.click(screen.getByRole("button", { name: "View Chat details" }));
    expect(screen.getByRole("dialog", { name: "Agent details" })).toBeInTheDocument();
    expect(onOpen).not.toHaveBeenCalled();
  });
});

describe("a package in the palette", () => {
  const group: any = {
    key: "curio.examples@1",
    name: "Examples",
    label: "Examples",
    descriptors: [],
  };
  const payload: any = {
    packageId: "curio.examples",
    major: 1,
    version: "1.0.0",
    name: "Examples",
    publisher: "Curio",
    description: "",
    license: "MIT",
    permissions: [],
    dependencies: null,
    templates: [],
    dirName: "curio.examples@1",
    lineage: null,
    familyKey: "curio.examples@1",
    channel: "stable",
  };

  function renderAccordion() {
    return render(
      <InstalledPackageAccordion
        group={group}
        activePackageKey={null}
        setActivePackageKey={jest.fn()}
        catalogMetadataLoaded
        catalogPublishAllowed={false}
        isCatalogPublished
        publishingPackageKey={null}
        onPublishToCatalog={jest.fn()}
      />,
    );
  }

  test("opens the package's details from its header", async () => {
    packagesApi.listInstalled.mockResolvedValue({ packages: [payload] });
    renderAccordion();
    fireEvent.click(screen.getByRole("button", { name: "View Examples details" }));
    expect(await screen.findByRole("dialog", { name: "Package details" })).toBeInTheDocument();
  });

  test("falls back to the shared catalog for a package the account does not hold", async () => {
    packagesApi.listInstalled.mockResolvedValue({ packages: [] });
    packagesApi.catalog.mockResolvedValue({ packages: [payload] });
    renderAccordion();
    fireEvent.click(screen.getByRole("button", { name: "View Examples details" }));
    await waitFor(() =>
      expect(screen.getByRole("dialog", { name: "Package details" })).toBeInTheDocument(),
    );
  });
});

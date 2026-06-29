import React from "react";
import { render, screen } from "@testing-library/react";
import { DatasetInstallingRow } from "../../components/menus/nodes/datasetPalette/DatasetInstallingRow";
import { DatasetInstallingCard } from "../../components/datasets/catalog/DatasetInstallingCard";
import type { PendingInstall } from "../../services/datasetCatalog/datasetCatalogTypes";

const pending: PendingInstall = {
  key: "n1",
  producerNodeId: "n1",
  label: "Clean Trips",
  startedAt: 0,
};

describe("DatasetInstallingRow (palette placeholder)", () => {
  it("renders the label, an Installing… caption, and a status role", () => {
    render(<DatasetInstallingRow pending={pending} />);
    const status = screen.getByRole("status");
    expect(status).toHaveAttribute("aria-busy", "true");
    expect(status).toHaveAttribute("aria-label", "Installing Clean Trips");
    expect(screen.getByText("Clean Trips")).toBeInTheDocument();
    expect(screen.getByText("Installing…")).toBeInTheDocument();
  });

  it("is not draggable (non-interactive placeholder)", () => {
    const { container } = render(<DatasetInstallingRow pending={pending} />);
    expect(container.querySelector('[draggable="true"]')).toBeNull();
  });
});

describe("DatasetInstallingCard (drawer placeholder)", () => {
  it("renders the label, an Installing… caption, and a status role", () => {
    render(<DatasetInstallingCard pending={pending} />);
    const status = screen.getByRole("status");
    expect(status).toHaveAttribute("aria-busy", "true");
    expect(status).toHaveAttribute("aria-label", "Installing Clean Trips");
    expect(screen.getByText("Clean Trips")).toBeInTheDocument();
    expect(screen.getByText("Installing…")).toBeInTheDocument();
  });
});

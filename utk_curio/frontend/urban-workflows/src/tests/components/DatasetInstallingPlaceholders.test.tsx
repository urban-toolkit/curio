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
  it("renders the label, an Adding… caption, and a status role", () => {
    render(<DatasetInstallingRow pending={pending} />);
    const status = screen.getByRole("status");
    expect(status).toHaveAttribute("aria-busy", "true");
    expect(status).toHaveAttribute("aria-label", "Adding Clean Trips");
    expect(screen.getByText("Clean Trips")).toBeInTheDocument();
    expect(screen.getByText("Adding…")).toBeInTheDocument();
  });

  it("is not draggable (non-interactive placeholder)", () => {
    const { container } = render(<DatasetInstallingRow pending={pending} />);
    expect(container.querySelector('[draggable="true"]')).toBeNull();
  });
});

describe("DatasetInstallingCard (drawer placeholder)", () => {
  it("renders the label, an Adding… caption, and a status role", () => {
    render(<DatasetInstallingCard pending={pending} />);
    const status = screen.getByRole("status");
    expect(status).toHaveAttribute("aria-busy", "true");
    expect(status).toHaveAttribute("aria-label", "Adding Clean Trips");
    expect(screen.getByText("Clean Trips")).toBeInTheDocument();
    expect(screen.getByText("Adding…")).toBeInTheDocument();
  });
});

/**
 * #352: a failed install must say so rather than vanish. The placeholder used
 * to be cleared whatever the save returned, which is #217's reported symptom -
 * the catalog entry flashes and disappears - and the warning toast then had
 * nothing on screen to point at.
 */
const failed: PendingInstall = { ...pending, status: "failed" };

describe("a failed install placeholder", () => {
  it("says it could not be added, in the palette row", () => {
    render(<DatasetInstallingRow pending={failed} />);
    expect(screen.getByText("Couldn't be added")).toBeInTheDocument();
    expect(screen.queryByText("Adding…")).toBeNull();
  });

  it("says it could not be added, in the drawer card", () => {
    render(<DatasetInstallingCard pending={failed} />);
    expect(screen.getByText("Couldn't be added")).toBeInTheDocument();
    expect(screen.queryByText("Adding…")).toBeNull();
  });

  it("stops announcing itself as busy", () => {
    // aria-busy=true on a finished, failed operation tells a screen reader the
    // work is still going.
    render(<DatasetInstallingRow pending={failed} />);
    const status = screen.getByRole("status");
    expect(status).toHaveAttribute("aria-busy", "false");
    expect(status).toHaveAttribute("aria-label", "Could not add Clean Trips");
  });

  it("keeps the in-flight wording when no status is set", () => {
    // Guards the three above: `status` is optional, and every existing caller
    // omits it.
    render(<DatasetInstallingCard pending={pending} />);
    expect(screen.getByText("Adding…")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveAttribute("aria-busy", "true");
  });
});

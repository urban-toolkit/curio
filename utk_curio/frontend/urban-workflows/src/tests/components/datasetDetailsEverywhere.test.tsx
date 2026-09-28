import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";

/**
 * One way into a dataset's details, from anywhere, including a toast.
 *
 * Toasts named a dataset ("Registered bikes.csv in the Data Catalog.", "Added
 * Bike Routes to this project.") and offered no way to it, and a finished lake
 * download raised no toast at all where an import did. A toast now carries
 * "View details", which opens the same modal a card does, through the one
 * provider every surface uses.
 */

jest.mock("../../components/datasets/catalog/DatasetDetailModal", () => ({
  DatasetDetailModal: ({ datasetId, onClose }: { datasetId: string; onClose: () => void }) => (
    <div role="dialog" aria-label="Dataset details" data-dataset-id={datasetId}>
      <button type="button" onClick={onClose}>
        Close
      </button>
    </div>
  ),
}));

import { ToastProvider, useToastContext } from "../../providers/ToastProvider";
import { DatasetDetailsProvider } from "../../components/datasets/catalog/DatasetDetailsProvider";
import {
  useDatasetDetails,
  viewDatasetDetailsToast,
} from "../../components/datasets/catalog/datasetDetailsContext";

const Surface: React.FC = () => {
  const { showToast } = useToastContext();
  const { openDatasetDetails } = useDatasetDetails();
  const navigate = useNavigate();
  return (
    <>
      <button
        type="button"
        onClick={() =>
          showToast(
            "Registered bikes.csv in the Data Catalog.",
            "success",
            viewDatasetDetailsToast(openDatasetDetails, "imported.bikes"),
          )
        }
      >
        Import
      </button>
      <button type="button" onClick={() => openDatasetDetails("imported.bikes")}>
        Open
      </button>
      <button type="button" onClick={() => navigate("/elsewhere")}>
        Leave
      </button>
    </>
  );
};

function renderApp() {
  return render(
    <MemoryRouter initialEntries={["/here"]}>
      <ToastProvider>
        <DatasetDetailsProvider closeOnNavigate>
          <Routes>
            <Route path="*" element={<Surface />} />
          </Routes>
        </DatasetDetailsProvider>
      </ToastProvider>
    </MemoryRouter>,
  );
}

const details = () => screen.queryByRole("dialog", { name: "Dataset details" });

describe("a toast about a dataset", () => {
  test("offers View details, which opens the dataset's details", () => {
    renderApp();
    fireEvent.click(screen.getByRole("button", { name: "Import" }));
    fireEvent.click(screen.getByRole("button", { name: "View details" }));

    expect(details()).toHaveAttribute("data-dataset-id", "imported.bikes");
    // Using it settles the toast.
    expect(screen.queryByText("Registered bikes.csv in the Data Catalog.")).toBeNull();
  });

  test("a toast without an action shows no button", () => {
    const Plain: React.FC = () => {
      const { showToast } = useToastContext();
      return (
        <button type="button" onClick={() => showToast("Saved.", "success")}>
          Save
        </button>
      );
    };
    render(
      <ToastProvider>
        <Plain />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByText("Saved.")).toBeInTheDocument();
    expect(screen.queryByTestId("toast-action")).toBeNull();
  });
});

describe("the dataset details provider", () => {
  test("closes its modal when the page under it changes", () => {
    // The app root sits above every page, so a modal opened on one page must
    // not follow you onto the next.
    renderApp();
    fireEvent.click(screen.getByRole("button", { name: "Open" }));
    expect(details()).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Leave" }));
    expect(details()).toBeNull();
  });

  test("reports the close to whoever opened it", () => {
    const onClose = jest.fn();
    const Opener: React.FC = () => {
      const { openDatasetDetails } = useDatasetDetails();
      return (
        <button type="button" onClick={() => openDatasetDetails("imported.bikes", { onClose })}>
          Open it
        </button>
      );
    };
    render(
      <MemoryRouter>
        <DatasetDetailsProvider>
          <Opener />
        </DatasetDetailsProvider>
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Open it" }));
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(details()).toBeNull();
  });
});

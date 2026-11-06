/**
 * Drop-to-Add: what a dropped card does, and how the drop reaches the open
 * catalog drawer that runs the Add. A hosted guest's drop is refused before
 * anything is asked of a drawer: guests never install.
 */
import React, { useCallback } from "react";
import { render, renderHook } from "@testing-library/react";

import type { ProjectLoadState } from "../../components/projectLoadState";
import { useDropsWhileOpening } from "../../hook/useDropsWhileOpening";
import {
  guestAddRefusal,
  packageDropAction,
  requestPackageAdd,
  usePackageAddRequests,
  type PackageAddRequest,
} from "../../services/packages/packageAddRequests";

const request = (over: Partial<PackageAddRequest> = {}): PackageAddRequest => ({
  dirName: "test.wheelhouse-probe@1",
  kind: "node",
  onAdded: jest.fn(),
  ...over,
});

describe("what a dropped card does", () => {
  it.each([
    [{ inDataflow: true, hostedGuest: false }, "create"],
    [{ inDataflow: true, hostedGuest: true }, "create"],
    [{ inDataflow: false, hostedGuest: false }, "add"],
    [{ inDataflow: false, hostedGuest: true }, "refuse"],
  ] as const)("%o: %s", (state, action) => {
    expect(packageDropAction(state)).toBe(action);
  });

  it("tells a hosted guest why, in the words the install routes use", () => {
    expect(guestAddRefusal("Wheelhouse Probe")).toBe(
      "Adding Wheelhouse Probe is not available for guest users, because every guest shares one account. Sign in with an account to add it.",
    );
  });
});

describe("the request to the open drawer", () => {
  it("is not taken when no drawer listens", () => {
    expect(requestPackageAdd(request())).toBe(false);
  });

  it("is taken by the drawer that answers it, with what to do once the package is added", () => {
    const take = jest.fn(() => true);
    renderHook(() => usePackageAddRequests(take));
    const sent = request();
    expect(requestPackageAdd(sent)).toBe(true);
    expect(take).toHaveBeenCalledWith(sent);
  });

  it("is not taken by a drawer that declines it, or by one that is not open", () => {
    const declines = renderHook(() => usePackageAddRequests(() => false));
    expect(requestPackageAdd(request({ kind: "model" }))).toBe(false);
    declines.unmount();
    const closed = jest.fn(() => true);
    renderHook(() => usePackageAddRequests(closed, false));
    expect(requestPackageAdd(request())).toBe(false);
    expect(closed).not.toHaveBeenCalled();
  });

  it("goes to one drawer only", () => {
    const first = jest.fn(() => true);
    const second = jest.fn(() => true);
    renderHook(() => usePackageAddRequests(first));
    renderHook(() => usePackageAddRequests(second));
    expect(requestPackageAdd(request())).toBe(true);
    expect(first.mock.calls.length + second.mock.calls.length).toBe(1);
  });
});

/**
 * A card dropped while the dataflow its link names is still opening waits for
 * it (`useDropsWhileOpening`), and the canvas sends its request from an effect
 * of the commit the dataflow opens in. That commit gives the open drawer a new
 * *take* too, since the drawer's Add reads the dataflow's id. The canvas comes
 * first in the tree, as MainCanvas comes before the drawer that
 * ModelCatalogDrawerProvider portals after its children, and React runs every
 * cleanup of a commit's effects before any of its effects: a drawer that took
 * its listener off to put the new *take* on was not listening when the
 * request came, so the drop said "Add ... from the Model Catalog first."
 * instead of opening the Add review.
 */
describe("a card dropped while the dataflow opens", () => {
  it("reaches the open drawer in the commit the dataflow opens in, and the drawer's newest take answers it", () => {
    const answered: boolean[] = [];
    const takenFor: Array<string | null> = [];
    let keep: (drop: PackageAddRequest) => boolean = () => false;

    function Canvas({ load }: { load: ProjectLoadState }) {
      keep = useDropsWhileOpening<PackageAddRequest>(
        { load, viewerMode: load === "loaded" ? "owner" : undefined, roomRole: null },
        (drop) => {
          answered.push(requestPackageAdd(drop));
        },
      );
      return null;
    }
    function Drawer({ projectId }: { projectId: string | null }) {
      const take = useCallback(() => {
        takenFor.push(projectId);
        return true;
      }, [projectId]);
      usePackageAddRequests(take);
      return null;
    }
    const Page = ({ load, projectId }: { load: ProjectLoadState; projectId: string | null }) => (
      <>
        <Canvas load={load} />
        <Drawer projectId={projectId} />
      </>
    );

    const { rerender } = render(<Page load="loading" projectId={null} />);
    expect(keep(request({ kind: "model" }))).toBe(true);
    expect(answered).toEqual([]);

    // The dataflow is in, and its id reaches the drawer in the same commit.
    rerender(<Page load="loaded" projectId="dataflow-1" />);

    expect({ answered, takenFor }).toEqual({ answered: [true], takenFor: ["dataflow-1"] });
  });
});

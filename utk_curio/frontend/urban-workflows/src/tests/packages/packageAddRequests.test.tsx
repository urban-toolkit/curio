/**
 * Drop-to-Add: what a dropped card does, and how the drop reaches the open
 * catalog drawer that runs the Add. A hosted guest's drop is refused before
 * anything is asked of a drawer: guests never install.
 */
import { renderHook } from "@testing-library/react";

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

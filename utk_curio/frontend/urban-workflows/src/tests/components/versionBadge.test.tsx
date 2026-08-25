import React from "react";
import { act, render, screen, waitFor } from "@testing-library/react";

import VersionBadge from "../../components/VersionBadge";

/**
 * The badge says how node code is running, so it must not overstate it.
 *
 * `/version` reports the mode the sandbox *resolved*, which is the only honest
 * source: `auto` resolves to `off`, and a `fork` the platform cannot support
 * degrades to `off`. The case these tests exist for is the last one below --
 * an unrecognised or missing mode must render nothing rather than fall back to
 * a reassuring default.
 */

const mockVersion = (body: unknown, ok = true) => {
  global.fetch = jest.fn().mockResolvedValue({
    ok,
    json: async () => body,
  }) as unknown as typeof fetch;
};

/** Render and let the /version promise settle, so no state lands outside act. */
const renderBadge = async () => {
  let result: ReturnType<typeof render>;
  await act(async () => {
    result = render(<VersionBadge />);
  });
  return result!;
};

describe("VersionBadge", () => {
  afterEach(() => {
    jest.resetAllMocks();
  });

  test("shows the version and that execution is isolated", async () => {
    mockVersion({ version: "0.16.10", isolation: "fork" });
    await renderBadge();

    await waitFor(() => expect(screen.getByText(/0\.16\.10/)).toBeInTheDocument());
    expect(screen.getByText(/isolated/)).toBeInTheDocument();
  });

  test("names the in-process mode rather than staying silent about it", async () => {
    mockVersion({ version: "0.16.10", isolation: "off" });
    await renderBadge();

    await waitFor(() => expect(screen.getByText(/in-process/)).toBeInTheDocument());
    expect(screen.queryByText(/isolated/)).toBeNull();
  });

  test("explains itself on hover", async () => {
    mockVersion({ version: "0.16.10", isolation: "fork" });
    await renderBadge();

    const mode = await screen.findByText(/isolated/);
    expect(mode).toHaveAttribute("title", expect.stringContaining("confined child process"));
  });

  test("says nothing about the mode when the sandbox could not be reached", async () => {
    // The backend degrades to 'unknown' rather than failing the request, so the
    // version still renders. Claiming either mode here would be a guess.
    mockVersion({ version: "0.16.10", isolation: "unknown" });
    await renderBadge();

    await waitFor(() => expect(screen.getByText(/0\.16\.10/)).toBeInTheDocument());
    expect(screen.queryByText(/isolated/)).toBeNull();
    expect(screen.queryByText(/in-process/)).toBeNull();
  });

  test("renders nothing at all when there is no version to show", async () => {
    mockVersion({ version: "", isolation: "fork" });
    const { container } = await renderBadge();
    expect(container).toBeEmptyDOMElement();
  });
});

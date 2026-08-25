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
 *
 * The two labels differ by a leading "not", so every assertion here matches the
 * rendered text exactly. A substring match for "isolated" is satisfied by "not
 * isolated", which would let the two states pass each other's tests.
 */

const ISOLATED = "(isolated)";
const NOT_ISOLATED = "(not isolated)";

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
    expect(screen.getByText(ISOLATED)).toBeInTheDocument();
    expect(screen.queryByText(NOT_ISOLATED)).toBeNull();
  });

  test("says plainly when execution is not isolated", async () => {
    mockVersion({ version: "0.16.10", isolation: "off" });
    await renderBadge();

    await waitFor(() => expect(screen.getByText(NOT_ISOLATED)).toBeInTheDocument());
    expect(screen.queryByText(ISOLATED)).toBeNull();
  });

  test("an unavailable isolation still reads as not isolated", async () => {
    // Distinct reason, same fact. A third label would be one more thing to
    // interpret, when what a reader needs is that there is no boundary.
    mockVersion({ version: "0.16.10", isolation: "unavailable" });
    await renderBadge();

    const mode = await screen.findByText(NOT_ISOLATED);
    expect(mode).toHaveAttribute(
      "title",
      expect.stringContaining("this platform cannot provide it"),
    );
  });

  test("explains itself on hover", async () => {
    mockVersion({ version: "0.16.10", isolation: "fork" });
    await renderBadge();

    const mode = await screen.findByText(ISOLATED);
    expect(mode).toHaveAttribute(
      "title",
      expect.stringContaining("confined child process"),
    );
  });

  test("says nothing about the mode when the sandbox could not be reached", async () => {
    // The backend degrades to 'unknown' rather than failing the request, so the
    // version still renders. Claiming either mode here would be a guess.
    mockVersion({ version: "0.16.10", isolation: "unknown" });
    await renderBadge();

    await waitFor(() => expect(screen.getByText(/0\.16\.10/)).toBeInTheDocument());
    expect(screen.queryByText(ISOLATED)).toBeNull();
    expect(screen.queryByText(NOT_ISOLATED)).toBeNull();
  });

  test("renders nothing at all when there is no version to show", async () => {
    mockVersion({ version: "", isolation: "fork" });
    const { container } = await renderBadge();
    expect(container).toBeEmptyDOMElement();
  });
});

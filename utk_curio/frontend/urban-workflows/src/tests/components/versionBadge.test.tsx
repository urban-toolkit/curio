import React from "react";
import { act, render, screen, waitFor } from "@testing-library/react";

import VersionBadge from "../../components/VersionBadge";

/**
 * The badge says how node code is running, so it must not overstate it.
 *
 * `/version` reports two things. `isolation` is the mode the sandbox
 * *resolved*: `auto` resolves to `off`, and a `fork` the platform cannot
 * support degrades to `off`. `isolation_active` is what execution actually
 * did, and it is the only field that can reveal a stack which resolved `fork`
 * and is running in-process anyway, because the confined child is started
 * lazily and a failure there is not fatal.
 *
 * Two cases these tests exist for, pulling in opposite directions: an
 * unrecognised or missing mode must render nothing rather than fall back to a
 * reassuring default, and a not-yet-known `isolation_active` must NOT be read
 * as a downgrade on an instance that is isolated.
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

  // ── isolation_active: the outcome, not the resolved mode ────────────────

  test("a resolved fork that fell back to in-process says NOT isolated", async () => {
    // The reason this field exists. The sandbox still reports `fork`, because
    // that is genuinely what it resolved, but the confined child never
    // started. A badge reading only `isolation` claims a boundary that is not
    // there.
    mockVersion({
      version: "0.16.10",
      isolation: "fork",
      isolation_active: "off",
    });
    await renderBadge();

    await waitFor(() => expect(screen.getByText(NOT_ISOLATED)).toBeInTheDocument());
    expect(screen.queryByText(ISOLATED)).toBeNull();
  });

  test("the degraded tooltip says the child could not start, not that it was off", async () => {
    // "not isolated" is the right label but the wrong whole story: an operator
    // who configured isolation needs to know it failed, not think they never
    // asked for it.
    mockVersion({
      version: "0.16.10",
      isolation: "fork",
      isolation_active: "off",
    });
    await renderBadge();

    const badge = await screen.findByText(NOT_ISOLATED);
    expect(badge).toHaveAttribute("title", expect.stringContaining("could not be started"));
  });

  test("pending is not a downgrade: a fresh page on an isolated stack still says isolated", async () => {
    // The common case. `pending` means no node has run yet, which is true of
    // every freshly loaded page, and is not evidence of anything.
    mockVersion({
      version: "0.16.10",
      isolation: "fork",
      isolation_active: "pending",
    });
    await renderBadge();

    await waitFor(() => expect(screen.getByText(ISOLATED)).toBeInTheDocument());
    expect(screen.queryByText(NOT_ISOLATED)).toBeNull();
  });

  test("a confirmed fork says isolated", async () => {
    mockVersion({
      version: "0.16.10",
      isolation: "fork",
      isolation_active: "fork",
    });
    await renderBadge();

    await waitFor(() => expect(screen.getByText(ISOLATED)).toBeInTheDocument());
  });

  test("an older sandbox that sends no isolation_active still says isolated", async () => {
    // Backward compatibility, and the mirror of the bug above: absence is not
    // evidence of a failed zygote, and reading it as one would show "not
    // isolated" on an instance that is isolated.
    mockVersion({ version: "0.16.10", isolation: "fork" });
    await renderBadge();

    await waitFor(() => expect(screen.getByText(ISOLATED)).toBeInTheDocument());
  });

  test("an unreachable sandbox does not downgrade a resolved mode", async () => {
    // The backend sends 'unknown' for both when it cannot reach the sandbox.
    mockVersion({
      version: "0.16.10",
      isolation: "fork",
      isolation_active: "unknown",
    });
    await renderBadge();

    await waitFor(() => expect(screen.getByText(ISOLATED)).toBeInTheDocument());
  });

  test("an off stack stays off whatever the outcome field says", async () => {
    mockVersion({
      version: "0.16.10",
      isolation: "off",
      isolation_active: "off",
    });
    await renderBadge();

    await waitFor(() => expect(screen.getByText(NOT_ISOLATED)).toBeInTheDocument());
    expect(screen.queryByText(ISOLATED)).toBeNull();
  });
});

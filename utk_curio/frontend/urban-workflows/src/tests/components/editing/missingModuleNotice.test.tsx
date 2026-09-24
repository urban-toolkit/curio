/**
 * Naming the missing library, and offering to install it (#299).
 *
 * Two things this pins that are easy to get wrong under a refactor:
 *
 * - **"installed, but it cannot be imported" is not "couldn't install".** It
 *   installed. Saying otherwise contradicts the message underneath it and sends
 *   the user to reinstall a library that is already there. The wording is
 *   shared with the Installed-libraries modal because it is the same failure.
 * - **An unsafe module name is never echoed.** The name comes from a traceback,
 *   which node code controls, so the refusal renders nothing at all rather than
 *   printing an attacker-chosen string into the panel.
 */
import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";

import {
  MissingModuleNotice,
  type InstallState,
} from "../../../components/editing/MissingModuleNotice";
import type { MissingModuleNotice as Notice } from "../../../types/nodeTypes";

function notice(over: Partial<Notice> = {}): Notice {
  return {
    module: "sklearn",
    distribution: "scikit-learn",
    installable: true,
    reason: null,
    detail: null,
    ...over,
  };
}

function renderNotice(
  over: Partial<Notice> = {},
  state: InstallState = { kind: "idle" },
  extra: { retried?: boolean } = {},
) {
  const onInstall = jest.fn();
  const onRunNode = jest.fn();
  const result = render(
    <MissingModuleNotice
      notice={notice(over)}
      state={state}
      retried={extra.retried ?? false}
      onInstall={onInstall}
      onRunNode={onRunNode}
    />,
  );
  return { ...result, onInstall, onRunNode };
}

describe("MissingModuleNotice", () => {
  it("names the distribution, not the import name, on the button", () => {
    // The user has to install `scikit-learn`; `sklearn` is not a thing pip
    // knows about.
    renderNotice();
    expect(screen.getByRole("button", { name: "Install scikit-learn" }))
      .toBeInTheDocument();
    expect(screen.getByText("scikit-learn")).toBeInTheDocument();
  });

  it("installs the distribution when the button is pressed", () => {
    const { onInstall } = renderNotice();
    fireEvent.click(screen.getByRole("button", { name: "Install scikit-learn" }));
    expect(onInstall).toHaveBeenCalledTimes(1);
    expect(onInstall).toHaveBeenCalledWith("scikit-learn");
  });

  it("says the environment is shared, because it is", () => {
    renderNotice();
    const button = screen.getByRole("button", { name: "Install scikit-learn" });
    expect(button.getAttribute("title")).toMatch(/shared by everyone/i);
  });

  it("disables the button while pip is running", () => {
    renderNotice({}, { kind: "installing", distribution: "scikit-learn" });
    expect(screen.getByText("Installing scikit-learn…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Installing…" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: /^Install /})).toBeNull();
  });

  it("asks for a re-run after a successful install, rather than running itself", () => {
    const { onRunNode } = renderNotice({}, {
      kind: "done", distribution: "scikit-learn", verdict: { kind: "installed" },
    });
    expect(screen.getByText("Installed scikit-learn.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Run node" }));
    expect(onRunNode).toHaveBeenCalledTimes(1);
  });

  it("distinguishes an already-installed library from a fresh install", () => {
    renderNotice({}, {
      kind: "done", distribution: "scikit-learn",
      verdict: { kind: "already-installed" },
    });
    expect(screen.getByText("scikit-learn was already installed."))
      .toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run node" })).toBeInTheDocument();
  });

  it("reports a library that installed but cannot import, in those words", () => {
    renderNotice({}, {
      kind: "done", distribution: "rasterio",
      verdict: { kind: "cannot-import", reason: "libgdal.so.30: cannot open" },
    });
    expect(screen.getByText(/installed, but it cannot be imported/))
      .toBeInTheDocument();
    expect(screen.getByText(/libgdal/)).toBeInTheDocument();
    // Not an install failure, so no retry - and no Run node, because running it
    // again would fail the same way.
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("shows pip's own message when the install fails, and offers a retry", () => {
    const { onInstall } = renderNotice({}, {
      kind: "failed", distribution: "scikit-learn",
      message: "pip install failed: No matching distribution found",
    });
    expect(screen.getByText(/No matching distribution found/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onInstall).toHaveBeenCalledWith("scikit-learn");
  });

  it("stops offering the button once the module failed again after an install", () => {
    renderNotice({}, { kind: "idle" }, { retried: true });
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText(/still cannot import sklearn/)).toBeInTheDocument();
    expect(screen.getByText(/Restart Curio/)).toBeInTheDocument();
  });

  describe("refusals", () => {
    it("explains a stdlib module instead of offering pip", () => {
      renderNotice({
        module: "json", distribution: null, installable: false, reason: "stdlib",
      });
      expect(screen.queryByRole("button")).toBeNull();
      expect(screen.getByText(/part of Python itself/)).toBeInTheDocument();
    });

    it("explains a module Curio provides", () => {
      renderNotice({
        module: "curio", distribution: null, installable: false,
        reason: "curio-provided",
      });
      expect(screen.queryByRole("button")).toBeNull();
      expect(screen.getByText(/provided by Curio/)).toBeInTheDocument();
    });

    it("explains an installed-but-broken library and carries the reason", () => {
      renderNotice({
        module: "rasterio", distribution: "rasterio", installable: false,
        reason: "installed-but-broken", detail: "libgdal.so.30: cannot open",
      });
      expect(screen.queryByRole("button")).toBeNull();
      expect(screen.getByText(/installing it again would change nothing/))
        .toBeInTheDocument();
      expect(screen.getByText(/libgdal/)).toBeInTheDocument();
    });

    it("tells the user to restart when the library is installed but unseen", () => {
      renderNotice({
        module: "flask", distribution: "Flask", installable: false,
        reason: "installed-not-visible",
      });
      expect(screen.queryByRole("button")).toBeNull();
      expect(screen.getByText(/Restart Curio/)).toBeInTheDocument();
    });

    it("renders NOTHING for a name that is not a distribution name", () => {
      // The module string came from a traceback, which node code controls.
      // Echoing "requests --index-url http://elsewhere" into the panel would
      // put an attacker-chosen string on screen for no benefit.
      const { container } = renderNotice({
        module: "requests --index-url http://elsewhere",
        distribution: null, installable: false, reason: "unsafe-name",
      });
      expect(container).toBeEmptyDOMElement();
    });
  });
});

describe("when the caller may not install (#309)", () => {
  it("says why rather than offering a button the route would refuse", () => {
    renderNotice({
      installable: false,
      reason: "install-disabled",
      detail:
        "Installing libraries is not available for guest users. Sign in with "
        + "an account to install one.",
    });
    expect(screen.getByText(/scikit-learn is not installed/)).toBeInTheDocument();
    expect(screen.getByText(/not available for guest users/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Install/ })).toBeNull();
  });
});

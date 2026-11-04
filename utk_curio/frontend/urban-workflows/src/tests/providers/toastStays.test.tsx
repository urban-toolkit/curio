/**
 * A toast that tells someone what another person did to their work, such as
 * "Fabio removed this node while you were editing it." with Put it back,
 * stays until it is dismissed (`ToastOptions.stay`), as an error does. A
 * warning without it still clears itself after five seconds.
 */
import React from "react";
import { act, render, screen } from "@testing-library/react";

import { ToastProvider, useToastContext } from "../../providers/ToastProvider";

let show: ReturnType<typeof useToastContext>["showToast"];
const Probe = () => {
  show = useToastContext().showToast;
  return null;
};

test("a toast that stays is still shown after a warning has cleared itself", () => {
  jest.useFakeTimers();
  try {
    render(
      <ToastProvider>
        <Probe />
      </ToastProvider>,
    );
    act(() => show("Fabio removed this node while you were editing it.", "warning", {
      action: { label: "Put it back", onClick: () => undefined },
      stay: true,
    }));
    act(() => show("Saved a copy.", "warning"));
    expect(screen.getByText("Saved a copy.")).toBeTruthy();

    act(() => {
      jest.advanceTimersByTime(6000);
    });

    expect(screen.queryByText("Saved a copy.")).toBeNull();
    expect(screen.getByText("Fabio removed this node while you were editing it.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Put it back" })).toBeTruthy();
  } finally {
    jest.useRealTimers();
  }
});

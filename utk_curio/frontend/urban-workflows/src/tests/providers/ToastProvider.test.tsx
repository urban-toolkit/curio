import React from "react";
import { render, screen, act } from "@testing-library/react";
import { ToastProvider, useToastContext, ToastVariant } from "../../providers/ToastProvider";

/**
 * Regression coverage for the toast layering fix: dataset action feedback
 * must stay visible above the Dataset Catalog drawer and other overlays.
 *
 * The two guarantees that keep a toast on top are (1) it portals to <body>
 * so it escapes any ancestor stacking context, and (2) it uses the top of
 * the shared layering scale (--curio-z-toast). The numeric ordering of that
 * scale is enforced separately in tests/styles/zLayerScale.test.ts.
 */

// Fire a toast from a nested child so we exercise the real provider render.
function Trigger({ message, variant }: { message: string; variant?: ToastVariant }) {
  const { showToast } = useToastContext();
  return (
    <button onClick={() => showToast(message, variant)}>fire</button>
  );
}

function getNotificationRegion(): HTMLElement {
  const region = document.body.querySelector('[aria-label="Notifications"]');
  if (!region) throw new Error("toast container not found");
  return region as HTMLElement;
}

describe("ToastProvider", () => {
  it("portals the toast container to <body> so it escapes ancestor stacking contexts", () => {
    // Wrap the provider in an element that establishes its own stacking
    // context; the toast container must still land on document.body.
    const { container } = render(
      <div style={{ transform: "translateZ(0)", position: "relative", zIndex: 1 }}>
        <ToastProvider>
          <Trigger message="Registered dataset in the data catalog." variant="success" />
        </ToastProvider>
      </div>,
    );

    act(() => {
      screen.getByText("fire").click();
    });

    const region = getNotificationRegion();
    expect(region.parentElement).toBe(document.body);
    expect(container.contains(region)).toBe(false);
    expect(screen.getByText("Registered dataset in the data catalog.")).toBeInTheDocument();
  });

  it("places the toast layer at the top of the shared scale", () => {
    render(
      <ToastProvider>
        <Trigger message="hello" variant="info" />
      </ToastProvider>,
    );
    act(() => {
      screen.getByText("fire").click();
    });
    const region = getNotificationRegion();
    expect(region.style.zIndex).toBe("var(--curio-z-toast)");
  });

  it("exposes an aria-live region and escalates errors to role=alert", () => {
    render(
      <ToastProvider>
        <Trigger message="Import failed" variant="error" />
      </ToastProvider>,
    );
    const region = getNotificationRegion();
    expect(region).toHaveAttribute("aria-live", "polite");

    act(() => {
      screen.getByText("fire").click();
    });
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it.each<[ToastVariant]>([["success"], ["info"], ["warning"]])(
    "auto-dismisses a %s toast after 5s",
    (variant) => {
      jest.useFakeTimers();
      try {
        render(
          <ToastProvider>
            <Trigger message="Transient" variant={variant} />
          </ToastProvider>,
        );
        act(() => {
          screen.getByText("fire").click();
        });
        expect(screen.getByText("Transient")).toBeInTheDocument();
        act(() => {
          jest.advanceTimersByTime(5000);
        });
        expect(screen.queryByText("Transient")).not.toBeInTheDocument();
      } finally {
        jest.useRealTimers();
      }
    },
  );

  it("keeps an error toast up until the user closes it", () => {
    // An error reports something that went wrong and usually names what to do
    // about it - "brokenlib cannot be imported (ImportError: DLL load failed
    // ...)" is one of them. Five seconds is not enough to read that, let alone
    // act on it, and there is no history to go back to.
    jest.useFakeTimers();
    try {
      render(
        <ToastProvider>
          <Trigger message="brokenlib cannot be imported" variant="error" />
        </ToastProvider>,
      );
      act(() => {
        screen.getByText("fire").click();
      });
      act(() => {
        jest.advanceTimersByTime(60_000);
      });
      expect(screen.getByText("brokenlib cannot be imported")).toBeInTheDocument();
    } finally {
      jest.useRealTimers();
    }
  });

  it("still lets the user close an error toast", () => {
    // Staying up is only tolerable because there is a way out; without this the
    // change would leave every error on screen for the rest of the session.
    render(
      <ToastProvider>
        <Trigger message="Import failed" variant="error" />
      </ToastProvider>,
    );
    act(() => {
      screen.getByText("fire").click();
    });
    const close = screen.getByRole("button", { name: /close/i });
    act(() => {
      close.click();
    });
    expect(screen.queryByText("Import failed")).not.toBeInTheDocument();
  });
});

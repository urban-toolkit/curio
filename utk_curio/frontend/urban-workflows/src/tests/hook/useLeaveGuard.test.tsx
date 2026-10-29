import fs from "fs";
import path from "path";
import React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

import { LEAVE_DATAFLOW, useLeaveGuard } from "../../hook/useLeaveGuard";

/**
 * One question before unsaved work is dropped, asked the same way everywhere.
 *
 * The top menu and the dashboard bar each carried their own copy of this
 * dialog, and the dashboard's empty state and the links inside a dataset's
 * details had none, so whether leaving asked first depended on which control
 * you happened to use.
 *
 * A dataflow bound to its doc holds nothing unsaved: its leave waits for the
 * server to have this tab's last change (`settle`), and asks only when the
 * server cannot be reached in time.
 */

const Harness: React.FC<{ unsaved: boolean; onGo: () => void; settle?: () => Promise<boolean> }> = ({
  unsaved,
  onGo,
  settle,
}) => {
  const { leave, dialog } = useLeaveGuard(unsaved, LEAVE_DATAFLOW, { settle });
  return (
    <>
      <button type="button" onClick={() => leave(onGo)}>
        Go
      </button>
      {dialog}
    </>
  );
};

describe("useLeaveGuard", () => {
  test("goes at once when nothing is unsaved", () => {
    const onGo = jest.fn();
    render(<Harness unsaved={false} onGo={onGo} />);
    fireEvent.click(screen.getByRole("button", { name: "Go" }));
    expect(onGo).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  test("asks first, and staying goes nowhere", () => {
    const onGo = jest.fn();
    render(<Harness unsaved onGo={onGo} />);
    fireEvent.click(screen.getByRole("button", { name: "Go" }));

    expect(screen.getByRole("dialog", { name: LEAVE_DATAFLOW.title })).toBeInTheDocument();
    expect(screen.getByText(LEAVE_DATAFLOW.body)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Stay here" }));
    expect(onGo).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  test("discarding goes on", () => {
    const onGo = jest.fn();
    render(<Harness unsaved onGo={onGo} />);
    fireEvent.click(screen.getByRole("button", { name: "Go" }));
    fireEvent.click(screen.getByRole("button", { name: "Discard and continue" }));
    expect(onGo).toHaveBeenCalledTimes(1);
  });
});

describe("leaving a dataflow bound to its doc", () => {
  test("waits for the server to have the last change, then goes without asking", async () => {
    const onGo = jest.fn();
    let kept!: (answer: boolean) => void;
    const settle = jest.fn(() => new Promise<boolean>((resolve) => { kept = resolve; }));
    render(<Harness unsaved={false} onGo={onGo} settle={settle} />);

    fireEvent.click(screen.getByRole("button", { name: "Go" }));
    expect(settle).toHaveBeenCalledTimes(1);
    // A change still on its way would be lost on leaving now.
    expect(onGo).not.toHaveBeenCalled();

    await act(async () => { kept(true); });
    expect(onGo).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  test("asks when the server cannot have the last change in time", async () => {
    const onGo = jest.fn();
    render(<Harness unsaved={false} onGo={onGo} settle={() => Promise.resolve(false)} />);

    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Go" })); });

    expect(screen.getByRole("dialog", { name: LEAVE_DATAFLOW.title })).toBeInTheDocument();
    expect(onGo).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Discard and continue" }));
    expect(onGo).toHaveBeenCalledTimes(1);
  });

  test("asks when the wait fails", async () => {
    const onGo = jest.fn();
    render(<Harness unsaved={false} onGo={onGo} settle={() => Promise.reject(new Error("gone"))} />);

    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Go" })); });

    expect(screen.getByRole("dialog", { name: LEAVE_DATAFLOW.title })).toBeInTheDocument();
    expect(onGo).not.toHaveBeenCalled();
  });

  test("asks at once for what no one keeps, with no wait", () => {
    const onGo = jest.fn();
    const settle = jest.fn(() => Promise.resolve(true));
    render(<Harness unsaved onGo={onGo} settle={settle} />);

    fireEvent.click(screen.getByRole("button", { name: "Go" }));

    expect(screen.getByRole("dialog", { name: LEAVE_DATAFLOW.title })).toBeInTheDocument();
    expect(settle).not.toHaveBeenCalled();
  });
});

describe("the leave dialog has one implementation", () => {
  test("no other file builds its own", () => {
    const SRC = path.resolve(__dirname, "../..");
    const offenders: string[] = [];
    const walk = (dir: string) => {
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) {
          if (entry.name !== "tests") walk(full);
        } else if (/\.tsx?$/.test(entry.name) && !full.endsWith("useLeaveGuard.tsx")) {
          if (fs.readFileSync(full, "utf8").includes("Discard and continue")) {
            offenders.push(path.relative(SRC, full));
          }
        }
      }
    };
    walk(SRC);
    expect(offenders).toEqual([]);
  });
});

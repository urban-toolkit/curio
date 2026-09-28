import fs from "fs";
import path from "path";
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

import { LEAVE_DATAFLOW, useLeaveGuard } from "../../hook/useLeaveGuard";

/**
 * One question before unsaved work is dropped, asked the same way everywhere.
 *
 * The top menu and the dashboard bar each carried their own copy of this
 * dialog, and the dashboard's empty state and the links inside a dataset's
 * details had none, so whether leaving asked first depended on which control
 * you happened to use.
 */

const Harness: React.FC<{ unsaved: boolean; onGo: () => void }> = ({ unsaved, onGo }) => {
  const { leave, dialog } = useLeaveGuard(unsaved, LEAVE_DATAFLOW);
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

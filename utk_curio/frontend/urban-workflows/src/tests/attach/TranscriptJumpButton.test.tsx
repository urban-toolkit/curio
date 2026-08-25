import React from "react";
import { render, screen } from "@testing-library/react";
import { TranscriptJumpButton } from "../../components/agents/attach/TranscriptJumpButton";

describe("TranscriptJumpButton count label (dev/83)", () => {
  it("renders nothing while hidden", () => {
    const { container } = render(
      <TranscriptJumpButton visible={false} onJump={() => {}} count={3} />,
    );
    expect(container.querySelector("button")).toBeNull();
  });

  it("REGRESSION: without a count the dev/75 pill is unchanged", () => {
    render(<TranscriptJumpButton visible onJump={() => {}} />);
    const pill = screen.getByRole("button", { name: "Jump to latest messages" });
    expect(pill).toHaveTextContent("Latest");
  });

  it("count 0 still reads Latest — never '0 new'", () => {
    render(<TranscriptJumpButton visible onJump={() => {}} count={0} />);
    expect(
      screen.getByRole("button", { name: "Jump to latest messages" }),
    ).toHaveTextContent("Latest");
  });

  it("count 1 reads '1 new' with a singular accessible name", () => {
    render(<TranscriptJumpButton visible onJump={() => {}} count={1} />);
    expect(
      screen.getByRole("button", { name: "Jump to 1 new message" }),
    ).toHaveTextContent("1 new");
  });

  it("count 3 reads '3 new' with the count in the accessible name", () => {
    render(<TranscriptJumpButton visible onJump={() => {}} count={3} />);
    expect(
      screen.getByRole("button", { name: "Jump to 3 new messages" }),
    ).toHaveTextContent("3 new");
  });

  it("display caps at 99+ while the accessible name keeps the real number", () => {
    render(<TranscriptJumpButton visible onJump={() => {}} count={150} />);
    expect(
      screen.getByRole("button", { name: "Jump to 150 new messages" }),
    ).toHaveTextContent("99+ new");
  });
});

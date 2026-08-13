import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";

// Keep the provider module graphs out of this presentational suite — the
// subject is the dev/75 follow-at-bottom contract, not the LLM plumbing.
jest.mock("../../providers/LLMProvider", () => ({
  useLLMContext: () => ({
    llmRequest: jest.fn().mockResolvedValue({ result: "hi" }),
    setCurrentEventPipeline: jest.fn(),
  }),
}));
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ setWorkflowGoal: jest.fn(), cleanCanvas: jest.fn() }),
}));
jest.mock("../../utils/authApi", () => ({ getToken: () => null }));

import ChatComponent from "../../components/LLMChat";

const BOTTOM = 700; // mocked scrollHeight 1000 − clientHeight 300

function mockGeometry(el: HTMLElement) {
  let scrollTop = 0;
  Object.defineProperty(el, "scrollHeight", { configurable: true, get: () => 1000 });
  Object.defineProperty(el, "clientHeight", { configurable: true, get: () => 300 });
  Object.defineProperty(el, "scrollTop", {
    configurable: true,
    get: () => scrollTop,
    set: (v: number) => {
      scrollTop = v;
    },
  });
  (el as HTMLElement & { scrollTo: (opts: ScrollToOptions) => void }).scrollTo = (
    opts: ScrollToOptions,
  ) => {
    scrollTop = opts.top ?? 0;
  };
}

describe("LLMChat follow-at-bottom auto-scroll (memo dev/75)", () => {
  beforeEach(() => {
    global.fetch = jest.fn().mockResolvedValue({}) as unknown as typeof fetch;
  });

  function renderChat() {
    const utils = render(<ChatComponent />);
    // The transcript scroller is the panel's programmatically-focusable div.
    const transcript = utils.container.querySelector(
      '[tabindex="-1"]',
    ) as HTMLDivElement;
    mockGeometry(transcript);
    return { ...utils, transcript };
  }

  it("shows the Jump-to-latest pill only while scrolled away from the bottom", () => {
    const { transcript } = renderChat();
    expect(screen.queryByRole("button", { name: /jump to latest/i })).toBeNull();

    transcript.scrollTop = 100;
    fireEvent.scroll(transcript);
    expect(
      screen.getByRole("button", { name: /jump to latest/i }),
    ).toBeInTheDocument();

    transcript.scrollTop = BOTTOM;
    fireEvent.scroll(transcript);
    expect(screen.queryByRole("button", { name: /jump to latest/i })).toBeNull();
  });

  it("clicking the pill scrolls to the latest message and hides it", () => {
    const { transcript } = renderChat();
    transcript.scrollTop = 100;
    fireEvent.scroll(transcript);
    fireEvent.click(screen.getByRole("button", { name: /jump to latest/i }));
    expect(transcript.scrollTop).toBe(BOTTOM);
    expect(screen.queryByRole("button", { name: /jump to latest/i })).toBeNull();
  });
});

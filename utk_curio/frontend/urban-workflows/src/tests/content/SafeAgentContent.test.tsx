import React from "react";
import { render, screen } from "@testing-library/react";

import { sanitizeAgentUrl } from "../../components/agents/content/sanitizeAgentContent";
import { SafeAgentContent } from "../../components/agents/content/SafeAgentContent";
import { AgentChatCard } from "../../components/agents/content/AgentChatCard";

describe("sanitizeAgentUrl (REQ-SEC-002 URL policy)", () => {
  it("allows http(s) and mailto", () => {
    expect(sanitizeAgentUrl("https://example.com/x")).toBe("https://example.com/x");
    expect(sanitizeAgentUrl("http://example.com")).toBe("http://example.com");
    expect(sanitizeAgentUrl("mailto:a@b.c")).toBe("mailto:a@b.c");
  });

  it("neutralizes unsafe schemes", () => {
    for (const bad of [
      "javascript:alert(1)",
      "data:text/html,<script>alert(1)</script>",
      "vbscript:msgbox",
      "file:///etc/passwd",
      "blob:https://x",
      " \tjavascript:alert(1)",
      "JAVASCRIPT:alert(1)",
    ]) {
      expect(sanitizeAgentUrl(bad)).toBeUndefined();
    }
  });

  it("keeps relative URLs (they resolve to the app origin)", () => {
    expect(sanitizeAgentUrl("/docs/page")).toBe("/docs/page");
  });
});

describe("SafeAgentContent (hostile-content fixtures, RISK-RENDER-001)", () => {
  it("renders ordinary markdown", () => {
    const { container } = render(
      <SafeAgentContent text={"Some **bold** text and `code`.\n\n- item"} />,
    );
    expect(container.querySelector("strong")?.textContent).toBe("bold");
    expect(container.querySelector("code")?.textContent).toBe("code");
    expect(container.querySelector("li")?.textContent).toBe("item");
  });

  it("never renders raw HTML or scripts", () => {
    const { container } = render(
      <SafeAgentContent
        text={'Hello <script>window.__pwned = true;</script><img src=x onerror="window.__pwned2=true">'}
      />,
    );
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect((window as unknown as { __pwned?: boolean }).__pwned).toBeUndefined();
    expect((window as unknown as { __pwned2?: boolean }).__pwned2).toBeUndefined();
  });

  it("neutralizes javascript: links but keeps the link text", () => {
    const { container } = render(<SafeAgentContent text={"[click me](javascript:alert(1))"} />);
    const anchors = Array.from(container.querySelectorAll("a"));
    expect(anchors.every((a) => !a.getAttribute("href"))).toBe(true);
    expect(container.textContent).toContain("click me");
  });

  it("safe links open in a new tab with noopener", () => {
    const { container } = render(<SafeAgentContent text={"[docs](https://example.com)"} />);
    const a = container.querySelector("a");
    expect(a?.getAttribute("href")).toBe("https://example.com");
    expect(a?.getAttribute("target")).toBe("_blank");
    expect(a?.getAttribute("rel")).toContain("noopener");
  });

  it("drops images whose src was sanitized away", () => {
    const { container } = render(<SafeAgentContent text={"![x](javascript:alert(1))"} />);
    expect(container.querySelector("img")).toBeNull();
  });

  it("renders code fences as inert text", () => {
    const { container } = render(
      <SafeAgentContent text={'```html\n<script>alert(1)</script>\n```'} />,
    );
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("pre")?.textContent).toContain("<script>");
  });
});

describe("AgentChatCard (docs/03 visual contract, generic shell)", () => {
  const card = {
    type: "card" as const,
    kind: "result",
    title: "Created dataset node",
    lines: ["noaa.parquet → DATA palette", "Provenance: agent-created"],
  };

  it("renders title, kind label, and lines as plain text", () => {
    render(<AgentChatCard card={card} />);
    expect(screen.getByText("Created dataset node")).toBeInTheDocument();
    expect(screen.getByText("result")).toBeInTheDocument();
    expect(screen.getByText("noaa.parquet → DATA palette")).toBeInTheDocument();
  });

  it("card fields never render as markup", () => {
    const hostile = {
      type: "card" as const,
      kind: "result",
      title: "<b>bold?</b>",
      lines: ['<script>window.__cardPwned = true;</script>'],
    };
    const { container } = render(<AgentChatCard card={hostile} />);
    expect(container.querySelector("b")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect(container.textContent).toContain("<b>bold?</b>");
  });

  it("unknown kinds render the same generic shell", () => {
    render(<AgentChatCard card={{ ...card, kind: "preview" }} />);
    expect(screen.getByText("preview")).toBeInTheDocument();
    expect(screen.getByText("Created dataset node")).toBeInTheDocument();
  });

  it("carries no action buttons (docs/08 invariant)", () => {
    const { container } = render(<AgentChatCard card={card} />);
    expect(container.querySelector("button")).toBeNull();
  });
});

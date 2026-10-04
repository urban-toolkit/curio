import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { LlmConfigAction, remedyOf } from "../../components/llmConfigs/LlmConfigAction";
import {
  API_SETTINGS_EVENT,
  type ApiSettingsFocus,
} from "../../components/apiSettings/apiSettingsRequest";

/**
 * A run refused because no LLM configuration answers an agent carries
 * `remedy: {kind: "llm-config", agentId}`; the one button for it opens API
 * Settings on that agent's row.
 */

it("opens API Settings on the agent the refusal names", () => {
  const asked: ApiSettingsFocus[] = [];
  const listener = (event: Event) => asked.push((event as CustomEvent<ApiSettingsFocus>).detail);
  window.addEventListener(API_SETTINGS_EVENT, listener);
  render(<LlmConfigAction remedy={{ kind: "llm-config", agentId: "agent.node-content-builder" }} />);
  fireEvent.click(screen.getByRole("button", { name: "Open API Settings" }));
  expect(asked).toEqual([{ section: "agent-models", agentId: "agent.node-content-builder" }]);
  window.removeEventListener(API_SETTINGS_EVENT, listener);
});

it("renders nothing for another remedy, or none", () => {
  const { container } = render(
    <>
      <LlmConfigAction remedy={{ kind: "connection-key", host: "api.census.gov" }} />
      <LlmConfigAction remedy={null} />
    </>,
  );
  expect(container.textContent).toBe("");
});

it("reads the remedy off a refused request's body", () => {
  const refused = Object.assign(new Error("No LLM configuration answers this run."), {
    status: 400,
    body: { error: "No LLM configuration answers this run.", remedy: { kind: "llm-config", agentId: "agent.chat-agent" } },
  });
  expect(remedyOf(refused)).toEqual({ kind: "llm-config", agentId: "agent.chat-agent" });
  expect(remedyOf(new Error("plain"))).toBeNull();
  expect(remedyOf(null)).toBeNull();
});

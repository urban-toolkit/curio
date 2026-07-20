/**
 * Unit tests for the /api/agents client. `apiFetch` is mocked so each method's
 * URL / verb / body / param-escaping is asserted without a real request.
 */

jest.mock("../../utils/authApi", () => ({
  apiFetch: jest.fn(() => Promise.resolve({ agents: [] })),
  getToken: jest.fn(),
}));

import { apiFetch } from "../../utils/authApi";
import { agentsApi } from "../../api/agentsApi";

const mockFetch = apiFetch as jest.Mock;

beforeEach(() => mockFetch.mockClear());

describe("agentsApi", () => {
  it("catalog() hits the global catalog, with optional projectId", () => {
    agentsApi.catalog();
    expect(mockFetch).toHaveBeenCalledWith("/api/agents/catalog");
    agentsApi.catalog("proj 1");
    expect(mockFetch).toHaveBeenLastCalledWith("/api/agents/catalog?projectId=proj%201");
  });

  it("listImports() GETs the My Imports scope", () => {
    agentsApi.listImports();
    expect(mockFetch).toHaveBeenCalledWith("/api/agents/imports");
  });

  it("import() POSTs the coord", () => {
    agentsApi.import("agent.node-explainer@1.0.0");
    expect(mockFetch).toHaveBeenCalledWith("/api/agents/imports", {
      method: "POST",
      body: JSON.stringify({ coord: "agent.node-explainer@1.0.0" }),
    });
  });

  it("removeImport() DELETEs an escaped coord", () => {
    agentsApi.removeImport("agent.node-explainer@1.0.0");
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/agents/imports/agent.node-explainer%401.0.0",
      { method: "DELETE" },
    );
  });

  it("listProjectAgents() GETs the project scope", () => {
    agentsApi.listProjectAgents("p1");
    expect(mockFetch).toHaveBeenCalledWith("/api/agents/projects/p1");
  });

  it("installToProject() POSTs the coord to the install path", () => {
    agentsApi.installToProject("p1", "agent.chat-agent@1.0.0");
    expect(mockFetch).toHaveBeenCalledWith("/api/agents/projects/p1/install", {
      method: "POST",
      body: JSON.stringify({ coord: "agent.chat-agent@1.0.0" }),
    });
  });

  it("uninstallFromProject() DELETEs the escaped coord under the project", () => {
    agentsApi.uninstallFromProject("p1", "agent.chat-agent@1.0.0");
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/agents/projects/p1/agent.chat-agent%401.0.0",
      { method: "DELETE" },
    );
  });

  it("publish() POSTs the coord to publications", () => {
    agentsApi.publish("agent.my-custom@1.0.0");
    expect(mockFetch).toHaveBeenCalledWith("/api/agents/publications", {
      method: "POST",
      body: JSON.stringify({ coord: "agent.my-custom@1.0.0" }),
    });
  });

  it("unpublish() DELETEs the escaped coord under publications", () => {
    agentsApi.unpublish("agent.my-custom@1.0.0");
    expect(mockFetch).toHaveBeenCalledWith("/api/agents/publications/agent.my-custom%401.0.0", {
      method: "DELETE",
    });
  });
});

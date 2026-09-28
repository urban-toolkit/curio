/** The LLM configurations client: URL, verb, body; never a key read back. */
jest.mock("../../utils/authApi", () => ({
  apiFetch: jest.fn(() => Promise.resolve({})),
  getToken: jest.fn(),
}));

import { apiFetch } from "../../utils/authApi";
import { llmConfigsApi } from "../../api/llmConfigsApi";

const mocked = apiFetch as jest.Mock;

beforeEach(() => mocked.mockClear());

describe("llmConfigsApi", () => {
  it("reads the listing", async () => {
    await llmConfigsApi.listing();
    expect(mocked).toHaveBeenCalledWith("/api/agents/llm");
  });

  it("creates with the fields it is given, the key included once", async () => {
    await llmConfigsApi.create({
      label: "Work",
      endpoint: "own",
      apiType: "openai_compatible",
      baseUrl: "https://api.openai.com/v1",
      apiKey: "sk-test-value",
      model: "gpt-4o-mini",
    });
    const [url, init] = mocked.mock.calls[0];
    expect(url).toBe("/api/agents/llm/configs");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({
      label: "Work",
      endpoint: "own",
      apiType: "openai_compatible",
      baseUrl: "https://api.openai.com/v1",
      apiKey: "sk-test-value",
      model: "gpt-4o-mini",
    });
  });

  it("patches and deletes by id, escaping it", async () => {
    await llmConfigsApi.update("llm-00000000000a", { model: "gpt-4o", clearApiKey: true });
    const [url, init] = mocked.mock.calls[0];
    expect(url).toBe("/api/agents/llm/configs/llm-00000000000a");
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body)).toEqual({ model: "gpt-4o", clearApiKey: true });

    await llmConfigsApi.remove("a b");
    expect(mocked).toHaveBeenLastCalledWith("/api/agents/llm/configs/a%20b", { method: "DELETE" });
  });

  it("duplicates server-side with an optional label and model", async () => {
    await llmConfigsApi.duplicate("llm-00000000000a");
    let [url, init] = mocked.mock.calls[0];
    expect(url).toBe("/api/agents/llm/configs/llm-00000000000a/duplicate");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({});

    await llmConfigsApi.duplicate("llm-00000000000a", { label: "Copy", model: "gpt-4o" });
    [url, init] = mocked.mock.calls[1];
    expect(JSON.parse(init.body)).toEqual({ label: "Copy", model: "gpt-4o" });
  });

  it("sets the default, null meaning the Deployment default", async () => {
    await llmConfigsApi.setDefault("llm-00000000000a");
    let [url, init] = mocked.mock.calls[0];
    expect(url).toBe("/api/agents/llm/default");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body)).toEqual({ configId: "llm-00000000000a" });

    await llmConfigsApi.setDefault(null);
    [url, init] = mocked.mock.calls[1];
    expect(JSON.parse(init.body)).toEqual({ configId: null });
  });

  it("lists models by configuration or by this Curio install, never with a key it did not type", async () => {
    await llmConfigsApi.models({ endpoint: "deployment" });
    let [url, init] = mocked.mock.calls[0];
    expect(url).toBe("/api/agents/provider-models");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ endpoint: "deployment" });

    await llmConfigsApi.models({
      apiType: "openai_compatible",
      baseUrl: "http://localhost:11434/v1",
      configId: "llm-00000000000a",
    });
    [url, init] = mocked.mock.calls[1];
    expect(JSON.parse(init.body)).toEqual({
      apiType: "openai_compatible",
      baseUrl: "http://localhost:11434/v1",
      configId: "llm-00000000000a",
    });
  });
});

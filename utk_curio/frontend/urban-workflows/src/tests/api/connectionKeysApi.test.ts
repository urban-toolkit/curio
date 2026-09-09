/** dev/116: the connection-keys client — URL, verb, body; never a value read back. */
jest.mock("../../utils/authApi", () => ({
  apiFetch: jest.fn(() => Promise.resolve({ keys: [] })),
  getToken: jest.fn(),
}));

import { apiFetch } from "../../utils/authApi";
import { connectionKeysApi } from "../../api/connectionKeysApi";

const mocked = apiFetch as jest.Mock;

beforeEach(() => mocked.mockClear());

describe("connectionKeysApi", () => {
  it("lists refs", async () => {
    await connectionKeysApi.list();
    expect(mocked).toHaveBeenCalledWith("/api/users/me/connection-keys");
  });

  it("puts a key by name with host, value, delivery and the replace flag", async () => {
    await connectionKeysApi.put("census", { host: "api.census.gov", value: "s3cr3t", delivery: "query:key", replace: true });
    const [url, init] = mocked.mock.calls[0];
    expect(url).toBe("/api/users/me/connection-keys/census");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body)).toEqual({ host: "api.census.gov", value: "s3cr3t", delivery: "query:key", replace: true });
  });

  it("removes by name and suggests a name for a host, escaping both", async () => {
    await connectionKeysApi.remove("a b");
    expect(mocked).toHaveBeenCalledWith("/api/users/me/connection-keys/a%20b", { method: "DELETE" });
    await connectionKeysApi.suggestName("https://api.census.gov/data");
    expect(mocked).toHaveBeenLastCalledWith(
      "/api/users/me/connection-keys/suggest-name?host=https%3A%2F%2Fapi.census.gov%2Fdata",
    );
  });
});

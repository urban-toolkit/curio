/**
 * #429: where the collaboration socket connects, for each shape the backend
 * address takes (see utils/backendUrl). socket.io reads the URL's path as the
 * namespace and sends the handshake to `path` at the URL's origin.
 */
import { collabSocketTarget } from "../../utils/collabSocketTarget";

test("a backend under a path: the namespace at the origin, the prefix in path", () => {
  expect(collabSocketTarget("https://lab.example.edu/curio/api", "/collab")).toEqual({
    url: "https://lab.example.edu/collab",
    path: "/curio/api/socket.io",
  });
});

test("a backend at the root of its origin keeps the default path", () => {
  expect(collabSocketTarget("http://localhost:5002", "/collab")).toEqual({
    url: "http://localhost:5002/collab",
    path: "/socket.io",
  });
});

test("a same-origin backend ('') resolves against the page", () => {
  expect(collabSocketTarget("", "/collab", "https://app.example.org/dataflow/1")).toEqual({
    url: "https://app.example.org/collab",
    path: "/socket.io",
  });
});

test("a relative backend path ('/api') resolves against the page too", () => {
  expect(collabSocketTarget("/api", "/collab", "https://dev.example.org/dataflow/1")).toEqual({
    url: "https://dev.example.org/collab",
    path: "/api/socket.io",
  });
});

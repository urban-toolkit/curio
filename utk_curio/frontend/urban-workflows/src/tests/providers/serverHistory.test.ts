/**
 * Whose history a canvas has (`providers/history/serverHistory.ts`): the
 * server's while it is bound to the dataflow's doc, the browser's otherwise.
 * File > Save of a bound dataflow is a version of its own, sent after every
 * change the tab made; a watcher's tab sends none.
 */
jest.mock("../../api/historyApi", () => ({
  historyApi: { saved: jest.fn() },
}));

import { historyApi } from "../../api/historyApi";
import {
  noteSaved,
  serverHistory,
  setServerHistory,
  subscribeServerHistory,
  type ServerHistory,
} from "../../providers/history/serverHistory";

const saved = historyApi.saved as jest.Mock;

function bound(reads = true): ServerHistory & { whenKept: jest.Mock } {
  return { projectId: "proj", reads: () => reads, whenKept: jest.fn().mockResolvedValue(true), codeOf: () => undefined };
}

afterEach(() => {
  setServerHistory(null);
  saved.mockReset();
});

test("the history is the browser's until a canvas binds, and every listener hears each change", () => {
  expect(serverHistory()).toBeNull();
  const heard = jest.fn();
  const stop = subscribeServerHistory(heard);
  const history = bound();
  setServerHistory(history);
  expect(serverHistory()).toBe(history);
  // The same binding again changes nothing.
  setServerHistory(history);
  setServerHistory(null);
  expect(heard).toHaveBeenCalledTimes(2);
  stop();
  setServerHistory(bound());
  expect(heard).toHaveBeenCalledTimes(2);
});

test("File > Save of a bound dataflow is a version, sent after the tab's changes are kept", async () => {
  saved.mockResolvedValue({ id: "p9" });
  const history = bound();
  setServerHistory(history);
  await noteSaved();
  expect(saved).toHaveBeenCalledWith("proj");
  expect(history.whenKept.mock.invocationCallOrder[0]).toBeLessThan(saved.mock.invocationCallOrder[0]);
});

test("a canvas bound to no doc, and a watcher's tab, send no version", async () => {
  await noteSaved();
  const watcher = bound(false);
  setServerHistory(watcher);
  await noteSaved();
  expect(watcher.whenKept).not.toHaveBeenCalled();
  expect(saved).not.toHaveBeenCalled();
});

test("a version the server could not record leaves the save as it was", async () => {
  saved.mockRejectedValue(new Error("This dataflow has no saved spec."));
  setServerHistory(bound());
  const warn = jest.spyOn(console, "warn").mockImplementation(() => undefined);
  await expect(noteSaved()).resolves.toBeUndefined();
  expect(warn).toHaveBeenCalled();
  warn.mockRestore();
});

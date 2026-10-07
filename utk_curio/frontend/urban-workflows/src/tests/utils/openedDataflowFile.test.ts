/**
 * The hand-over from File > Load to ProjectLoader (#751): the menu leaves the
 * open dataflow and hands the picked file here, and the loader takes it once
 * `/dataflow/new` is set up. `projectLoaderOpensDataflowFile.test.tsx` covers
 * the loader's side.
 */
import {
  hasOpenedDataflowFile,
  openDataflowFile,
  openedDataflowFileRevision,
  subscribeOpenedDataflowFile,
  takeOpenedDataflowFile,
} from "../../utils/openedDataflowFile";

const FIRST = { dataflow: { name: "Tree canopy by block", nodes: [], edges: [] } };
const SECOND = { dataflow: { name: "Bus stops by route", nodes: [], edges: [] } };

beforeEach(() => {
  takeOpenedDataflowFile();
});

it("hands a picked file out once", () => {
  expect(hasOpenedDataflowFile()).toBe(false);
  openDataflowFile(FIRST);
  expect(hasOpenedDataflowFile()).toBe(true);
  expect(takeOpenedDataflowFile()).toBe(FIRST);
  // Taken, it is gone: the next new dataflow starts empty.
  expect(hasOpenedDataflowFile()).toBe(false);
  expect(takeOpenedDataflowFile()).toBeNull();
});

it("keeps the latest pick when two arrive before the loader takes one", () => {
  openDataflowFile(FIRST);
  openDataflowFile(SECOND);
  expect(takeOpenedDataflowFile()).toBe(SECOND);
  expect(takeOpenedDataflowFile()).toBeNull();
});

it("tells its subscribers about every pick until they unsubscribe", () => {
  const listener = jest.fn();
  const before = openedDataflowFileRevision();
  const unsubscribe = subscribeOpenedDataflowFile(listener);

  openDataflowFile(FIRST);
  expect(listener).toHaveBeenCalledTimes(1);
  expect(openedDataflowFileRevision()).toBe(before + 1);

  unsubscribe();
  openDataflowFile(SECOND);
  expect(listener).toHaveBeenCalledTimes(1);
  // Still counted: a loader that subscribes later reads the revision fresh.
  expect(openedDataflowFileRevision()).toBe(before + 2);
});

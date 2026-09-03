/**
 * What a dataset's copy control hands over (#206).
 *
 * The issue asks for "a way to copy the path". The path is the wrong thing to
 * hand out, and handing it out is part of why the request exists: an absolute
 * path is specific to one machine, one user and one mount, so pasting it into a
 * node produces code that works until someone else opens the dataflow. The
 * portable reference is ``curio_dataset_path("<id>")`` — exactly what the
 * palette's own generated loaders emit, and what the sandbox resolves at
 * execution time.
 *
 * The location is still shown in the details view, as information.
 */
import {
  datasetReference,
  datasetReferenceCode,
} from "../../services/datasetCatalog/datasetReference";

const item = (over: Record<string, unknown> = {}) =>
  ({ id: "data.urbanlab.acs@1", path: "C:/Users/fabio/.curio/data/acs.parquet", ...over }) as never;

describe("datasetReference", () => {
  test("hands over the portable call, not the path", () => {
    expect(datasetReference(item()).code).toBe('curio_dataset_path("data.urbanlab.acs@1")');
  });

  test("still reports where the bytes are", () => {
    expect(datasetReference(item()).location).toBe("C:/Users/fabio/.curio/data/acs.parquet");
  });

  test("falls back to uri when there is no path", () => {
    expect(datasetReference(item({ path: undefined, uri: "curio://outputs/x" })).location).toBe(
      "curio://outputs/x",
    );
  });

  test("reports an empty location rather than inventing one", () => {
    // A live node output has no on-disk location yet; the details view hides
    // the row rather than showing "undefined".
    expect(datasetReference(item({ path: undefined, uri: undefined })).location).toBe("");
  });
});

describe("ids that cannot be embedded", () => {
  // Ids are interpolated into Python source, so one carrying a quote or a
  // backslash would break out of the string literal. Same whitelist the
  // generator applies, and the same fallback it makes.
  test("falls back to a quoted literal path", () => {
    const ref = datasetReference(item({ id: 'evil");import os#' }));
    expect(ref.code).toBe('"C:/Users/fabio/.curio/data/acs.parquet"');
  });

  test("an id starting with punctuation is not embedded", () => {
    expect(datasetReference(item({ id: ".hidden" })).code).not.toContain("curio_dataset_path");
  });

  test("a missing id is not embedded", () => {
    expect(datasetReference(item({ id: undefined })).code).not.toContain("curio_dataset_path");
  });
});

describe("datasetReferenceCode", () => {
  test("is the code half of the reference", () => {
    expect(datasetReferenceCode(item())).toBe(datasetReference(item()).code);
  });
});

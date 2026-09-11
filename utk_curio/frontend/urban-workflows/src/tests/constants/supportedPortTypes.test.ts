/**
 * One vocabulary for port data types (#219).
 *
 * There were two independent derivations of the same enum: the settings dialog
 * built its own option list, and ``packagesClient.asSupportedTypes`` built a
 * separate Set to filter incoming manifests. Nothing kept them in step -- and
 * because the dialog's field was free text anyway, a typo passed the editor and
 * was dropped on the way into the registry, so a port silently lost a type.
 */
import { SupportedType } from "../../constants";
import {
  SUPPORTED_PORT_TYPES,
  isSupportedPortType,
  normalizePortTypes,
} from "../../constants/supportedPortTypes";

describe("the vocabulary", () => {
  test("is exactly the SupportedType enum", () => {
    expect([...SUPPORTED_PORT_TYPES]).toEqual(Object.values(SupportedType));
  });

  test("is closed", () => {
    // ConnectionValidator compares these values directly, so a type outside the
    // enum could never match a port. That is why the control is a <select> and
    // not a combobox with a custom-value escape hatch.
    expect(isSupportedPortType("DATAFRAME")).toBe(true);
    expect(isSupportedPortType("dataframe")).toBe(false);
    expect(isSupportedPortType("table")).toBe(false);
  });
});

describe("normalizePortTypes", () => {
  test("passes an array through", () => {
    expect(normalizePortTypes(["DATAFRAME", "JSON"])).toEqual(["DATAFRAME", "JSON"]);
  });

  test("splits the legacy comma string", () => {
    // A canvas node's packageTemplateConfig persisted before the shape change
    // still carries one string. Reading it as a single type would render a
    // select with no matching option, and the next edit would overwrite it.
    expect(normalizePortTypes("DATAFRAME, GEODATAFRAME")).toEqual([
      "DATAFRAME",
      "GEODATAFRAME",
    ]);
  });

  test("drops blanks and duplicates", () => {
    expect(normalizePortTypes("DATAFRAME,,DATAFRAME, ")).toEqual(["DATAFRAME"]);
  });

  test("keeps an unrecognised value rather than dropping it", () => {
    // Deliberately NOT filtered here. Silently discarding is what made the old
    // free-text field lossy; the editor shows it as "unrecognised" so the
    // author can see what they wrote and fix it.
    expect(normalizePortTypes("TABLE")).toEqual(["TABLE"]);
  });

  test("treats anything else as empty", () => {
    expect(normalizePortTypes(undefined)).toEqual([]);
    expect(normalizePortTypes(null)).toEqual([]);
    expect(normalizePortTypes(42)).toEqual([]);
  });
});

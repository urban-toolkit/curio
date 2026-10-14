/**
 * A node package's card dragged from the Node Catalog drawer carries the
 * package and the nodes its drop can make: the one node it makes, or the
 * several a menu at the drop point offers. A card of a package with no node
 * does not drag.
 */
import {
  PACKAGE_CARD_DRAG_MIME,
  beginPackageCardDrag,
  createPackageCardDragPayload,
  endPackageCardDrag,
  hasPackageCardDrag,
  packageCardNodes,
  readPackageCardDragPayload,
  writePackageCardDragData,
} from "../../services/packages/packageCardDrag";
import type { PackagePayload, PackageTemplatePayload } from "../../services/packages";

/** A minimal DataTransfer: jsdom has none. */
function fakeDataTransfer() {
  const store = new Map<string, string>();
  return {
    effectAllowed: "",
    dropEffect: "",
    get types() {
      return Array.from(store.keys());
    },
    setData: (type: string, value: string) => void store.set(type, value),
    getData: (type: string) => store.get(type) ?? "",
  } as unknown as DataTransfer;
}

const template = (id: string, label: string, paletteOrder: number | null = null) =>
  ({ id, templateId: id.split("/")[1].split("@")[0], label, paletteOrder } as unknown as PackageTemplatePayload);

const pkg = (templates: PackageTemplatePayload[], over: Partial<PackagePayload> = {}): PackagePayload =>
  ({
    packageId: "test.wheelhouse-probe",
    major: 1,
    dirName: "test.wheelhouse-probe@1",
    name: "Wheelhouse Probe",
    templates,
    ...over,
  } as unknown as PackagePayload);

const PROBE = template("test.wheelhouse-probe/probe@1", "Wheelhouse Probe");
const PAIR = { packageId: "test.wheelhouse-pair", dirName: "test.wheelhouse-pair@1", name: "Wheelhouse Pair" };
const FIRST = template("test.wheelhouse-pair/first@1", "Pair First Probe");
const SECOND = template("test.wheelhouse-pair/second@1", "Pair Second Probe");

afterEach(() => endPackageCardDrag());

describe("the nodes a card drops", () => {
  it("are the package's one node", () => {
    expect(packageCardNodes(pkg([PROBE]))).toEqual([
      { nodeType: "test.wheelhouse-probe/probe@1", label: "Wheelhouse Probe" },
    ]);
  });

  it("are every node of a package with several, in the palette's order", () => {
    const third = template("test.wheelhouse-pair/third@1", "Pair Third Probe", 0);
    expect(packageCardNodes(pkg([FIRST, SECOND, third], PAIR))).toEqual([
      { nodeType: "test.wheelhouse-pair/third@1", label: "Pair Third Probe" },
      { nodeType: "test.wheelhouse-pair/first@1", label: "Pair First Probe" },
      { nodeType: "test.wheelhouse-pair/second@1", label: "Pair Second Probe" },
    ]);
  });

  it("are none for a package with no node, whose card does not drag", () => {
    expect(packageCardNodes(pkg([]))).toEqual([]);
    expect(createPackageCardDragPayload(pkg([]))).toBeNull();
    expect(beginPackageCardDrag(pkg([]))).toBeNull();
  });
});

describe("the drag", () => {
  it("carries the package and its one node, as a copy", () => {
    const payload = beginPackageCardDrag(pkg([PROBE]));
    expect(payload).toEqual({
      dirName: "test.wheelhouse-probe@1",
      name: "Wheelhouse Probe",
      kind: "node",
      nodes: [{ nodeType: "test.wheelhouse-probe/probe@1", label: "Wheelhouse Probe" }],
    });
    const dataTransfer = fakeDataTransfer();
    writePackageCardDragData(dataTransfer, payload!);
    expect(dataTransfer.effectAllowed).toBe("copy");
    expect(dataTransfer.types).toContain(PACKAGE_CARD_DRAG_MIME);
    expect(hasPackageCardDrag(dataTransfer)).toBe(true);
    expect(readPackageCardDragPayload(dataTransfer)).toEqual(payload);
  });

  it("carries every node of a package with several", () => {
    const payload = beginPackageCardDrag(pkg([FIRST, SECOND], PAIR));
    expect(payload).toEqual({
      dirName: "test.wheelhouse-pair@1",
      name: "Wheelhouse Pair",
      kind: "node",
      nodes: [
        { nodeType: "test.wheelhouse-pair/first@1", label: "Pair First Probe" },
        { nodeType: "test.wheelhouse-pair/second@1", label: "Pair Second Probe" },
      ],
    });
    const dataTransfer = fakeDataTransfer();
    writePackageCardDragData(dataTransfer, payload!);
    expect(hasPackageCardDrag(dataTransfer)).toBe(true);
    expect(readPackageCardDragPayload(dataTransfer)).toEqual(payload);
  });

  it("reads from the DataTransfer alone once the in-memory drag has ended", () => {
    const payload = createPackageCardDragPayload(pkg([FIRST, SECOND], PAIR))!;
    const dataTransfer = fakeDataTransfer();
    writePackageCardDragData(dataTransfer, payload);
    endPackageCardDrag();
    expect(readPackageCardDragPayload(dataTransfer)).toEqual(payload);
  });

  it("is not some other drag", () => {
    const dataTransfer = fakeDataTransfer();
    dataTransfer.setData("application/reactflow", "curio.builtin/data-loading@1");
    dataTransfer.setData("text/plain", "curio-model:{}");
    expect(hasPackageCardDrag(dataTransfer)).toBe(false);
    expect(readPackageCardDragPayload(dataTransfer)).toBeNull();
  });

  it("is not read from data that names no node", () => {
    const dataTransfer = fakeDataTransfer();
    dataTransfer.setData(
      PACKAGE_CARD_DRAG_MIME,
      JSON.stringify({ dirName: "test.wheelhouse-pair@1", name: "Wheelhouse Pair", kind: "node", nodes: [] }),
    );
    expect(readPackageCardDragPayload(dataTransfer)).toBeNull();
  });
});

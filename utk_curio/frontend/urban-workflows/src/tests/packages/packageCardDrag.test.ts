/**
 * A node package's card dragged from the Node Catalog drawer carries the
 * package and the one node its drop makes; a card of a package with several
 * nodes, or none, does not drag.
 */
import {
  PACKAGE_CARD_DRAG_MIME,
  beginPackageCardDrag,
  createPackageCardDragPayload,
  endPackageCardDrag,
  hasPackageCardDrag,
  packageCardNode,
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

const template = (id: string, label: string) =>
  ({ id, templateId: id.split("/")[1].split("@")[0], label } as unknown as PackageTemplatePayload);

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

afterEach(() => endPackageCardDrag());

describe("the node a card drops", () => {
  it("is the package's one node", () => {
    expect(packageCardNode(pkg([PROBE]))).toEqual({
      nodeType: "test.wheelhouse-probe/probe@1",
      label: "Wheelhouse Probe",
    });
  });

  it("is none for a package with several nodes or none, whose card does not drag", () => {
    const other = template("test.wheelhouse-probe/other@1", "Other");
    expect(packageCardNode(pkg([PROBE, other]))).toBeNull();
    expect(packageCardNode(pkg([]))).toBeNull();
    expect(createPackageCardDragPayload(pkg([PROBE, other]))).toBeNull();
    expect(beginPackageCardDrag(pkg([]))).toBeNull();
  });
});

describe("the drag", () => {
  it("carries the package and its node, as a copy", () => {
    const payload = beginPackageCardDrag(pkg([PROBE]));
    expect(payload).toEqual({
      dirName: "test.wheelhouse-probe@1",
      name: "Wheelhouse Probe",
      kind: "node",
      nodeType: "test.wheelhouse-probe/probe@1",
      nodeLabel: "Wheelhouse Probe",
    });
    const dataTransfer = fakeDataTransfer();
    writePackageCardDragData(dataTransfer, payload!);
    expect(dataTransfer.effectAllowed).toBe("copy");
    expect(dataTransfer.types).toContain(PACKAGE_CARD_DRAG_MIME);
    expect(hasPackageCardDrag(dataTransfer)).toBe(true);
    expect(readPackageCardDragPayload(dataTransfer)).toEqual(payload);
  });

  it("reads from the DataTransfer alone once the in-memory drag has ended", () => {
    const payload = createPackageCardDragPayload(pkg([PROBE]))!;
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
});

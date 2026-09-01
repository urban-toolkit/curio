import { rowsFromParseOutput } from "../../utils/tabularPreview";

describe("rowsFromParseOutput", () => {
  test("converts column-oriented dataframe preview", () => {
    const rows = rowsFromParseOutput({
      dataType: "dataframe",
      data: {
        zone: ["North", "South"],
        pm25: [12.1, 9.8],
      },
    });
    expect(rows).toEqual([
      { zone: "North", pm25: 12.1 },
      { zone: "South", pm25: 9.8 },
    ]);
  });

  test("converts geodataframe feature properties", () => {
    const rows = rowsFromParseOutput({
      dataType: "geodataframe",
      data: {
        features: [
          { properties: { tract_id: "17031010100" } },
        ],
      },
    });
    expect(rows).toEqual([{ tract_id: "17031010100" }]);
  });
});

import { extractNodeContent } from "../../utils/extractNodeContent";

const CODE = "import pandas as pd\ndf = pd.read_csv('x.csv')\nprint(df.head())";

describe("extractNodeContent (dev/57 — the legacy Get Code path's extractor)", () => {
  it("extracts the fenced body, dropping language ids and surrounding prose", () => {
    const reply = `Here is the code:\n\n\`\`\`python\n${CODE}\n\`\`\`\n\nThis loads the CSV.`;
    expect(extractNodeContent(reply)).toBe(CODE);
  });

  it("largest of multiple fences wins", () => {
    const reply = `Setup:\n\`\`\`bash\npip install pandas\n\`\`\`\nMain:\n\`\`\`python\n${CODE}\n\`\`\``;
    expect(extractNodeContent(reply)).toBe(CODE);
  });

  it("unwraps JSON wrappers, including wrapper-around-fence", () => {
    expect(extractNodeContent(JSON.stringify({ content: CODE }))).toBe(CODE);
    expect(
      extractNodeContent(JSON.stringify({ code: `\`\`\`python\n${CODE}\n\`\`\`` })),
    ).toBe(CODE);
  });

  it("returns unwrapped content byte-identical", () => {
    expect(extractNodeContent(CODE)).toBe(CODE);
    const dictLiteral = 'config = {"content": "x", "code": "y"}\nrun(config)';
    expect(extractNodeContent(dictLiteral)).toBe(dictLiteral);
  });

  it("preserves the legacy sentinel and handles non-strings", () => {
    expect(extractNodeContent("not controllable")).toBe("not controllable");
    expect(extractNodeContent(undefined)).toBe("");
  });
});

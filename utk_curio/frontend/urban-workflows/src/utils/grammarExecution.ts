export type GrammarType = "vega-lite" | "utk";

export type GrammarPreparationResult =
  | { ok: true; parsedSpec: any }
  | { ok: false; message: string };

function validateGrammarShape(
  parsed: any,
  grammarType: GrammarType
): GrammarPreparationResult {
  if (grammarType === "vega-lite") {
    const hasTopLevelSpec =
      parsed.mark !== undefined ||
      parsed.layer !== undefined ||
      parsed.facet !== undefined ||
      parsed.repeat !== undefined ||
      parsed.concat !== undefined ||
      parsed.hconcat !== undefined ||
      parsed.vconcat !== undefined;

    if (!hasTopLevelSpec) {
      return {
        ok: false,
        message:
          "Invalid Vega-Lite grammar: expected fields like 'mark', 'layer', 'facet', or a concat structure.",
      };
    }
  }

  if (grammarType === "utk") {
    if (
      parsed.grid === undefined ||
      parsed.components === undefined ||
      parsed.knots === undefined
    ) {
      return {
        ok: false,
        message:
          "Invalid UTK grammar: required fields 'grid', 'components', and 'knots' are missing.",
      };
    }
  }

  return { ok: true, parsedSpec: parsed };
}

export function prepareGrammarSpec(
  spec: string,
  grammarType: GrammarType
): GrammarPreparationResult {
  if (spec == null || spec.trim() === "") {
    return { ok: false, message: "Grammar specification cannot be empty." };
  }

  try {
    const parsed = JSON.parse(spec);

    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return {
        ok: false,
        message: "Grammar specification must be a valid JSON object.",
      };
    }

    return validateGrammarShape(parsed, grammarType);
  } catch (error: any) {
    return {
      ok: false,
      message: `Invalid JSON: ${error.message}`,
    };
  }
}

export function setGrammarError(
  setOutput: (value: { code: string; content: string; outputType?: string }) => void,
  message: string,
  showAlert: boolean = true
) {
  setOutput({ code: "error", content: message, outputType: "" });

  if (showAlert) {
    alert(message);
  }
}
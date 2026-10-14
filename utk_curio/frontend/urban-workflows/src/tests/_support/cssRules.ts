/**
 * What a stylesheet declares, read from its source: jest maps CSS modules to
 * `identity-obj-proxy`, so a rendered assertion cannot see which rules apply.
 */

/**
 * The value `property` takes for exactly `selector`, as the cascade leaves it
 * between rules of one specificity: the last rule that names the selector,
 * alone or in a selector list, wins. `undefined` when no rule sets it.
 *
 * For a flat stylesheet: a rule inside an at-rule is read as if it stood alone.
 */
export function declaredValue(css: string, selector: string, property: string): string | undefined {
  const source = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const rule = /([^{}]+)\{([^{}]*)\}/g;
  let value: string | undefined;
  let match: RegExpExecArray | null;
  while ((match = rule.exec(source)) !== null) {
    const selectors = match[1].split(",").map((s) => s.trim());
    if (!selectors.includes(selector)) continue;
    for (const declaration of match[2].split(";")) {
      const colon = declaration.indexOf(":");
      if (colon !== -1 && declaration.slice(0, colon).trim() === property) {
        value = declaration.slice(colon + 1).trim();
      }
    }
  }
  return value;
}

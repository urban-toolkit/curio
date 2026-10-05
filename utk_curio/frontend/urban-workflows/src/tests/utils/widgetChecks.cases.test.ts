/**
 * What is wrong with a widget, or with a value for one (#662), from one table
 * of cases, `utils/widgets/widgetChecks.cases.json`. The backend reads the same
 * table (`utk_curio/backend/tests/test_execution/test_widget_checks.py`)
 * through its twins of these checks, which judge an agent's widget
 * declarations: a widget an agent declares is checked as the Widgets tab
 * checks one a person adds.
 */
import cases from "../../utils/widgets/widgetChecks.cases.json";
import { checkWidgetDef, checkWidgetValue, type WidgetDef } from "../../utils/widgets/widgetModel";

type DefinitionCase = { name: string; def: WidgetDef; others?: WidgetDef[]; parameter?: boolean; expected: string | null };
type ValueCase = { name: string; widget: Pick<WidgetDef, "type" | "options">; value: unknown; expected: string | null };

describe("the shared widget check cases", () => {
  test.each((cases.definitions as unknown as DefinitionCase[]).map((c) => [c.name, c]))("a widget: %s", (_name, c) => {
    expect(checkWidgetDef(c.def, c.others ?? [], c.parameter ?? false)).toBe(c.expected);
  });

  test.each((cases.values as unknown as ValueCase[]).map((c) => [c.name, c]))("a value: %s", (_name, c) => {
    expect(checkWidgetValue(c.widget, c.value)).toBe(c.expected);
  });
});

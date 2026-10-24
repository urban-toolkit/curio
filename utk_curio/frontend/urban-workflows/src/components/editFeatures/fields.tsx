/**
 * The controls of the Map Editor node's forms (#662): a widget's, as its
 * Widgets tab draws them (`WidgetControl`): Material UI's text field, its
 * native select, its radio group and its checkbox, compact on the widget
 * theme. The node's body wraps them in that theme (`FieldTheme`).
 *
 * A field's test id and its name go on the element a person types in, picks
 * or ticks, never on Material UI's wrapper around it.
 */
import React from "react";
import Checkbox from "@mui/material/Checkbox";
import FormControlLabel from "@mui/material/FormControlLabel";
import Radio from "@mui/material/Radio";
import RadioGroup from "@mui/material/RadioGroup";
import TextField from "@mui/material/TextField";
import { ThemeProvider } from "@mui/material/styles";
import { widgetTheme } from "../editing/widgets/widgetTheme";

/** The widget theme, around a body whose forms use these controls. */
export function FieldTheme({ children }: { children: React.ReactNode }) {
  return <ThemeProvider theme={widgetTheme}>{children}</ThemeProvider>;
}

/** A text field; *type* `date` for a date. */
export function TextInput({
  value,
  onChange,
  label,
  testId,
  placeholder,
  type = "text",
  inputMode,
  id,
  className,
}: {
  value: string;
  onChange: (text: string) => void;
  /** Its accessible name. */
  label: string;
  testId?: string;
  placeholder?: string;
  type?: "text" | "date";
  inputMode?: "decimal";
  id?: string;
  className?: string;
}) {
  return (
    <TextField
      fullWidth
      id={id}
      type={type}
      value={value}
      placeholder={placeholder}
      className={className}
      inputProps={{ "aria-label": label, "data-testid": testId, inputMode }}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

/** A native list, which opens at any zoom of the canvas; its options are *children*. */
export function SelectInput({
  value,
  onChange,
  label,
  testId,
  disabled,
  id,
  className,
  children,
}: {
  value: string;
  onChange: (value: string) => void;
  label: string;
  testId?: string;
  disabled?: boolean;
  id?: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <TextField
      select
      fullWidth
      id={id}
      SelectProps={{ native: true }}
      value={value}
      disabled={disabled}
      className={className}
      inputProps={{ "aria-label": label, "data-testid": testId }}
      onChange={(e) => onChange(e.target.value)}
    >
      {children}
    </TextField>
  );
}

/** One choice of a radio group: its value, its label and the test id of its radio. */
export interface RadioOption {
  value: string;
  label: React.ReactNode;
  testId?: string;
}

/** A few choices, one picked: a radio group in a row. */
export function RadioChoices({
  value,
  onChange,
  label,
  testId,
  options,
}: {
  value: string;
  onChange: (value: string) => void;
  label: string;
  /** On the group. */
  testId?: string;
  options: RadioOption[];
}) {
  return (
    <RadioGroup row aria-label={label} data-testid={testId} value={value} onChange={(e) => onChange(e.target.value)}>
      {options.map((option) => (
        <FormControlLabel
          key={option.value || "empty"}
          value={option.value}
          label={option.label}
          control={<Radio inputProps={{ "data-testid": option.testId } as React.InputHTMLAttributes<HTMLInputElement>} />}
        />
      ))}
    </RadioGroup>
  );
}

/**
 * A checkbox; with *text*, the words beside it, else only its accessible name
 * *label*. *title* is its tooltip, the Curio one: MUI hands a `title` on to the
 * page, which draws the browser's own.
 */
export function CheckboxInput({
  checked,
  onChange,
  label,
  text,
  title,
  testId,
  role,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label?: string;
  text?: React.ReactNode;
  title?: string;
  testId?: string;
  /** `switch` for a setting that is on or off. */
  role?: "switch";
}) {
  const box = (
    <Checkbox
      checked={checked}
      data-tooltip={text ? undefined : title}
      inputProps={{ "aria-label": label, "data-testid": testId, role } as React.InputHTMLAttributes<HTMLInputElement>}
      onChange={(e) => onChange(e.target.checked)}
    />
  );
  return text ? <FormControlLabel data-tooltip={title} control={box} label={text} /> : box;
}

import { createTheme } from "@mui/material/styles";

/**
 * The look of a widget's control (WidgetControl): MUI's, as SCOUT draws its
 * widgets, made compact so a control fits inside a node. Small sizes and 12px
 * type throughout; the primary color is Curio's sky accent
 * (`--curio-accent-sky-fg`), which MUI needs as a literal to derive its shades.
 */
export const widgetTheme = createTheme({
  palette: {
    primary: { main: "#3567C7" },
  },
  typography: {
    fontSize: 12,
    fontFamily: "inherit",
  },
  components: {
    MuiTextField: {
      defaultProps: { size: "small", variant: "outlined" },
    },
    MuiInputBase: {
      styleOverrides: {
        root: { fontSize: 12, backgroundColor: "#fff" },
        input: { paddingTop: 6, paddingBottom: 6 },
      },
    },
    MuiOutlinedInput: {
      styleOverrides: {
        input: { paddingTop: 6, paddingBottom: 6, paddingLeft: 8, paddingRight: 8 },
      },
    },
    MuiInputAdornment: {
      styleOverrides: { root: { "& p": { fontSize: 11 } } },
    },
    MuiCheckbox: {
      defaultProps: { size: "small" },
      styleOverrides: { root: { padding: 4 } },
    },
    MuiRadio: {
      defaultProps: { size: "small" },
      styleOverrides: { root: { padding: 4 } },
    },
    MuiFormControlLabel: {
      styleOverrides: {
        root: { marginLeft: -4, marginRight: 10 },
        label: { fontSize: 12 },
      },
    },
    MuiSlider: {
      defaultProps: { size: "small" },
      styleOverrides: {
        root: { padding: "10px 0" },
        markLabel: { fontSize: 10 },
      },
    },
    MuiChip: {
      defaultProps: { size: "small" },
    },
    MuiButton: {
      defaultProps: { size: "small", disableElevation: true },
      styleOverrides: { root: { textTransform: "none", fontSize: 12 } },
    },
  },
});

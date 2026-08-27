/**
 * dev/52 DR-3 — the planning templates: labeled goal-prompt seeds for the
 * Dataflow Builder panel. Static v1 set (from the consolidated session,
 * dev/49); server-owned/governed templates are a later slice.
 */
export interface BuilderTemplate {
  id: string;
  label: string;
  /** The goal prompt seeded into the chat input (editable before send). */
  seed: string;
}

export const BUILDER_TEMPLATES: BuilderTemplate[] = [
  {
    id: "load-clean",
    label: "Load and Clean",
    seed: "Plan a dataflow that loads my dataset and cleans it: ",
  },
  {
    id: "geo-join-visualize",
    label: "Geospatial Join and Visualize",
    seed: "Plan a dataflow that joins my data to geography and visualizes it on a map: ",
  },
  {
    id: "stats-chart",
    label: "Compute Statistics and Chart",
    seed: "Plan a dataflow that computes summary statistics and charts them: ",
  },
  {
    id: "time-series",
    label: "Time-Series Exploration",
    seed: "Plan a dataflow that explores my data over time: ",
  },
  {
    id: "dashboard",
    label: "Build a Dashboard",
    seed: "Plan a dataflow that builds a dashboard for: ",
  },
  {
    id: "from-scratch",
    label: "From Scratch",
    seed: "Plan a dataflow that ",
  },
];

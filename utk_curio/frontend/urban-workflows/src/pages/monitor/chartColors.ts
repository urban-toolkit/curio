/**
 * The monitor's categorical palette, in its fixed order. Neighbouring colours
 * stay apart for colour-blind readers: checked on white, the closest adjacent
 * pair is 9.1 apart under colour blindness (OKLab, x100) and 19.6 apart to
 * full colour vision. Its first colour is the histograms' one hue.
 *
 * Charts take the colours in this order and never cycle them: a chart with
 * more series than colours folds the rest into one. Yellow, aqua and pink are
 * light on white, so a chart in these colours has its numbers in a table or
 * a label beside it too.
 */
export const CATEGORICAL = [
  "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948",
];

/**
 * A limit every line of a chart shares, drawn dashed: the axes' grey, so it
 * reads as a reference rather than as one more series.
 */
export const LIMIT_INK = "#6B6B76";

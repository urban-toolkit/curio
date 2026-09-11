/**
 * "updates" is gone. It was a filter over a state the cards already announce
 * ("Update to 1.2.0" sits in the card's own tag row) and that the detail drawer
 * already acts on, so the chip narrowed the grid to tell you a second time. It
 * left with Featured, for the same reason: a scope nothing falls into on its
 * own is a mood, not a filter.
 */
export type NodeCatalogFilterTab = "all" | "installed";

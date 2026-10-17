import { v4 as uuid } from "uuid";

/**
 * Which tab a save comes from, and its place among that tab's saves.
 *
 * The page gives up on a save after `SAVE_TIMEOUT_MS` (`projectsApi.ts`) and
 * the save queue sends the next one, but the server may still be working on
 * the first: on its way, or waiting for the project's lock. Every save of the
 * open dataflow carries this tab's id and a number one higher than the tab's
 * last save, and the server refuses a number lower than one it has already
 * applied from the same tab, so a save the page gave up on cannot land over a
 * newer one.
 *
 * The id is made once per page load and never stored: a reload counts from 1
 * again, under an id the server has not seen.
 */
const SAVE_TAB = uuid();
let lastSaveNumber = 0;

export interface SaveOrder {
  saveTab: string;
  saveNumber: number;
}

/** The order of the save about to be sent. */
export function nextSaveOrder(): SaveOrder {
  lastSaveNumber += 1;
  return { saveTab: SAVE_TAB, saveNumber: lastSaveNumber };
}

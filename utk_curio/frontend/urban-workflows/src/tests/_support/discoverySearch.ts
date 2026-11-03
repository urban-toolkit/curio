/**
 * Waiting on a Discovery search in a test.
 *
 * The search hook asks SEARCH_DEBOUNCE_MS (400 ms) after its query settles, so
 * what a search shows (its rows, a portal's note, an empty result) lands about
 * 0.4 s after the page renders. Testing Library's own wait gives up after 1 s,
 * which leaves a loaded CI runner about 0.6 s for everything else, and that is
 * not always enough.
 */

/** How late a search answers in the cases that play such a runner: with the
 *  debounce, its rows land 1.4 s after the page renders. */
export const LATE_SEARCH_MS = 1000;

/**
 * The mocked client answers every search LATE_SEARCH_MS late, through a real
 * timer, and every other call as it already did. Call it once the test's own
 * answers are in place.
 */
export function answerSearchesLate(apiFetch: jest.Mock): void {
  const answer = apiFetch.getMockImplementation() as
    | ((path: string, ...rest: unknown[]) => Promise<unknown>)
    | undefined;
  if (!answer) throw new Error('answerSearchesLate: give the client its answers first');
  apiFetch.mockImplementation((path: string, ...rest: unknown[]) =>
    path.includes('/search')
      ? new Promise((resolve) => setTimeout(resolve, LATE_SEARCH_MS)).then(() => answer(path, ...rest))
      : answer(path, ...rest)
  );
}

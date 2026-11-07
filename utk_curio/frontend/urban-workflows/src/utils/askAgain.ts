/**
 * A request asked again while its failure may pass the next time.
 *
 * A request that got no answer or a server error says nothing about what it
 * asked, and the next one usually passes: the browser drops every request in
 * flight when the machine's network changes, a restarting server answers 502
 * for a moment, and a server out of open files fails some requests while others
 * pass (#1274). The session check (`UserProvider`) and the projects page's list
 * ask again after each of `ASK_AGAIN_WAITS_MS` before they give up.
 *
 * Its own module, not part of `authApi`: many suites mock `authApi` with a
 * factory that lists only what they use.
 */

/** The waits between the tries of one request, 7.5 s in all. */
export const ASK_AGAIN_WAITS_MS = [500, 1000, 2000, 4000];

const wait = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/**
 * What *ask* answers, asked again after each of `ASK_AGAIN_WAITS_MS` while its
 * failure is one *mayPass* says may pass when sent again. Any other failure is
 * thrown at once, and so is the last try's. *stopped* (the caller went away, or
 * asked anew) ends it between tries, with the error the try had. Each try asked
 * again says so in the console, naming the request by *what*.
 */
export async function askAgain<T>(
  what: string,
  ask: () => Promise<T>,
  mayPass: (error: unknown) => boolean,
  stopped: () => boolean,
): Promise<T> {
  for (const ms of ASK_AGAIN_WAITS_MS) {
    try {
      return await ask();
    } catch (e) {
      if (!mayPass(e) || stopped()) throw e;
      console.warn(`[Curio] ${what} failed (${(e as Error)?.message ?? e}); asking again in ${ms} ms.`);
      await wait(ms);
      if (stopped()) throw e;
    }
  }
  return ask();
}

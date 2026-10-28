/**
 * What a page reports to the monitor as a browser error
 * (utils/clientErrorReporter.ts).
 *
 * The browser raises "ResizeObserver loop completed with undelivered
 * notifications." as a window `error` event with no error object when a
 * ResizeObserver delivers some sizes a frame late. Nothing threw, so it is not
 * reported: on a visitor's dashboard its report was a request beyond the
 * page's data (the Crown Heights dashboard e2e, run 40619435665). An event
 * that only resembles it, any other error and any unhandled rejection are
 * still reported, and the notice spends none of the reports a page may send.
 */

jest.mock("../../api/monitorApi", () => ({ postClientError: jest.fn() }));

const NOTICE = "ResizeObserver loop completed with undelivered notifications.";

type Listener = (event: any) => void;

/**
 * The reporter as a page load installs it: a fresh module, since its install
 * flag and its count of reports are per load; its listeners kept here rather
 * than added to jsdom's one window; and the post it reports through.
 */
function installed(): { on: Record<string, Listener>; post: jest.Mock; perLoad: number } {
  const on: Record<string, Listener> = {};
  const add = jest.spyOn(window, "addEventListener").mockImplementation(((type: string, listener: Listener) => {
    on[type] = listener;
  }) as any);
  let post!: jest.Mock;
  let perLoad = 0;
  try {
    jest.isolateModules(() => {
      post = require("../../api/monitorApi").postClientError;
      const reporter = require("../../utils/clientErrorReporter");
      perLoad = reporter.MAX_REPORTS_PER_LOAD;
      reporter.installClientErrorReporter();
    });
  } finally {
    add.mockRestore();
  }
  return { on, post, perLoad };
}

/** The window `error` event the browser raises for a ResizeObserver loop. */
const loopNotice = () => new ErrorEvent("error", { message: NOTICE, error: null });

const uncaught = (message: string) =>
  new ErrorEvent("error", { message: `Uncaught Error: ${message}`, error: new Error(message) });

const reported = (post: jest.Mock) => post.mock.calls.map(([report]) => report.message);

describe("the browser error reporter", () => {
  test("leaves out the browser's ResizeObserver loop notice", () => {
    const { on, post } = installed();
    on.error(loopNotice());
    expect(post).not.toHaveBeenCalled();
  });

  test("reports an event with the notice's words and an error, or with more words", () => {
    const { on, post } = installed();
    on.error(new ErrorEvent("error", { message: NOTICE, error: new Error(NOTICE) }));
    on.error(new ErrorEvent("error", { message: `${NOTICE} In the map's tile.`, error: null }));
    expect(reported(post)).toEqual([NOTICE, `${NOTICE} In the map's tile.`]);
  });

  test("reports an uncaught error and an unhandled rejection", () => {
    const { on, post } = installed();
    on.error(uncaught("a tile could not draw"));
    const rejection: any = new Event("unhandledrejection");
    rejection.reason = new Error("the run could not start");
    on.unhandledrejection(rejection);
    expect(reported(post)).toEqual(["Uncaught Error: a tile could not draw", "the run could not start"]);
  });

  test("reports an error that comes after more loop notices than a page may send reports", () => {
    const { on, post, perLoad } = installed();
    for (let notice = 0; notice < perLoad * 2; notice += 1) on.error(loopNotice());
    on.error(uncaught("a tile could not draw"));
    expect(reported(post)).toEqual(["Uncaught Error: a tile could not draw"]);
  });
});

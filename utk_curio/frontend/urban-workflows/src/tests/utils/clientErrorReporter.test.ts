/**
 * What a page reports to the monitor as a browser error
 * (utils/clientErrorReporter.ts).
 *
 * The browser raises "ResizeObserver loop completed with undelivered
 * notifications." as a window `error` event with no error object when a
 * ResizeObserver delivers some sizes a frame late. Nothing threw, so it is not
 * reported, and a visitor's dashboard asks the server for nothing beyond its
 * data for it. An event that only resembles it, any other error and any
 * unhandled rejection are still reported, and the notice spends none of the
 * reports a page may send.
 */

jest.mock("../../api/monitorApi", () => ({ postClientError: jest.fn() }));

const NOTICE = "ResizeObserver loop completed with undelivered notifications.";

type Listener = (event: any) => void;

/**
 * The reporter as a page load installs it: a fresh module, since its install
 * flag and its count of reports are per load; its listeners kept here rather
 * than added to jsdom's one window; and the post it reports through.
 */
function installed(): {
  on: Record<string, Listener>;
  post: jest.Mock;
  perLoad: number;
  reportHandledError: (message: string, stack?: string) => void;
} {
  const on: Record<string, Listener> = {};
  const add = jest.spyOn(window, "addEventListener").mockImplementation(((type: string, listener: Listener) => {
    on[type] = listener;
  }) as any);
  let post!: jest.Mock;
  let perLoad = 0;
  let reportHandledError!: (message: string, stack?: string) => void;
  try {
    jest.isolateModules(() => {
      post = require("../../api/monitorApi").postClientError;
      const reporter = require("../../utils/clientErrorReporter");
      perLoad = reporter.MAX_REPORTS_PER_LOAD;
      reportHandledError = reporter.reportHandledError;
      reporter.installClientErrorReporter();
    });
  } finally {
    add.mockRestore();
  }
  return { on, post, perLoad, reportHandledError };
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

  // A page that caught a failure and showed it (the projects page's list,
  // #1274) still tells the monitor, so its error log says why.
  test("reports an error a page handled, within the same reports a page may send", () => {
    const { on, post, perLoad, reportHandledError } = installed();
    reportHandledError("Couldn't load your dataflows: [Errno 24] Too many open files");
    expect(reported(post)).toEqual(["Couldn't load your dataflows: [Errno 24] Too many open files"]);

    for (let error = 0; error < perLoad * 2; error += 1) on.error(uncaught(`error ${error}`));
    reportHandledError("Couldn't load your dataflows: Bad gateway");
    expect(post).toHaveBeenCalledTimes(perLoad);
  });
});

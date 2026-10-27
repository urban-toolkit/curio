/**
 * Ending an autk-db database (adapters/node/autkDbClose) never fails the run
 * that drops it. The draws that end their databases are autkDuckdbWorkers'.
 */
import { closeAutkDb, closeGrammarDb } from '../../../adapters/node/autkDbClose';

test('ends the DuckDB worker a database holds, and a grammar\'s through its engine', () => {
  const terminate = jest.fn(async () => undefined);
  closeAutkDb({ db: { terminate } });
  closeGrammarDb({ grammarEngine: { context: { db: { terminate } } } });

  expect(terminate).toHaveBeenCalledTimes(2);
});

test('never throws, for one without a DuckDB worker or one whose worker will not end', async () => {
  expect(() => closeAutkDb(undefined)).not.toThrow();
  expect(() => closeAutkDb({})).not.toThrow();
  expect(() => closeGrammarDb({ grammarEngine: {} })).not.toThrow();
  expect(() => closeAutkDb({ db: { terminate: () => { throw new Error('gone'); } } })).not.toThrow();
  expect(() => closeAutkDb({ db: { terminate: () => Promise.reject(new Error('gone')) } })).not.toThrow();
  // The refused promise is handled: nothing reaches the page as unhandled.
  await Promise.resolve();
});

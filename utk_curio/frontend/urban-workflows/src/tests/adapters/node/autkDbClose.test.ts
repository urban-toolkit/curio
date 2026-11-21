/**
 * Ending an autk-db database (adapters/node/autkDbClose) never fails the run
 * that drops it, and the database a map node's run goes on is the node's own
 * (`runDatabase`): made when the run's workspaces or its first source need
 * one, handed to each call given none, and ended by the node. The draws that
 * end their databases are autkDuckdbWorkers', and a failed run of the grammar
 * build the app bundles, which ends its node's database, autkGrammarOptions'.
 */
// Each database autk-db made, and what its init fails with: nothing unless a test sets it.
const mockMade: Array<{ db: { terminate: jest.Mock } }> = [];
const mockInit: { fails: Error | null } = { fails: null };
jest.mock('@urban-toolkit/autk-db', () => ({
  DEFAULT_WORKSPACE_COORDINATE_FORMAT: 'EPSG:3395',
  DEFAULT_WORKSPACE_NAME: 'autk',
  AutkDb: class {
    db = { terminate: jest.fn(async () => undefined) };
    constructor() {
      mockMade.push(this);
    }
    async init() {
      if (mockInit.fails) throw mockInit.fails;
    }
  },
}), { virtual: true });

import * as dbClose from '../../../adapters/node/autkDbClose';

const { closeAutkDb } = dbClose;
// Read off the module as it is, so a checkout without them fails each case on its own.
const { newAutkDb, runDatabase } = dbClose as any;

beforeEach(() => {
  mockMade.length = 0;
  mockInit.fails = null;
});

test('ends the DuckDB worker a database holds', () => {
  const terminate = jest.fn(async () => undefined);
  closeAutkDb({ db: { terminate } });

  expect(terminate).toHaveBeenCalledTimes(1);
});

test('never throws, for one without a DuckDB worker or one whose worker will not end', async () => {
  expect(() => closeAutkDb(undefined)).not.toThrow();
  expect(() => closeAutkDb({})).not.toThrow();
  expect(() => closeAutkDb({ db: { terminate: () => { throw new Error('gone'); } } })).not.toThrow();
  expect(() => closeAutkDb({ db: { terminate: () => Promise.reject(new Error('gone')) } })).not.toThrow();
  // The refused promise is handled: nothing reaches the page as unhandled.
  await Promise.resolve();
});

test('a fresh database whose init fails is ended, and the failure passed on', async () => {
  mockInit.fails = new Error('failed to fetch https://extensions.duckdb.org/spatial');

  await expect(newAutkDb()).rejects.toThrow('extensions.duckdb.org');

  expect(mockMade.map((made) => made.db.terminate.mock.calls.length)).toEqual([1]);
});

describe("a map node's run database", () => {
  /** A data adapter of autk-grammar's that records the database each call is handed, and goes on with it. */
  const recording = () => {
    const handed: unknown[] = [];
    const adapter = {
      resolveWorkspaces: jest.fn(async (context: unknown) => { handed.push(context); return context; }),
      resolveSource: jest.fn(async (context: unknown) => { handed.push(context); return context; }),
    };
    return { adapter, handed };
  };

  test("is made when the run's workspaces first need one, and handed to each call given none, once", async () => {
    const made = { db: { terminate: jest.fn(async () => undefined) } };
    const make = jest.fn(async () => made);
    const database = runDatabase(make);
    const { adapter, handed } = recording();
    const wrapped = database.handedTo(adapter);
    const other = { other: true };

    expect(database.db).toBeUndefined();
    expect(await wrapped.resolveWorkspaces(undefined, [{ coordinateFormat: 'EPSG:3395' }])).toBe(made);
    expect(await wrapped.resolveSource(made, { type: 'geojson' })).toBe(made);
    expect(await wrapped.resolveSource(undefined, { type: 'geojson' })).toBe(made);
    expect(await wrapped.resolveSource(other, { type: 'geojson' })).toBe(other);

    expect(handed.map((context) => (context === made ? 'made' : context === other ? 'other' : context))).toEqual(
      ['made', 'made', 'made', 'other'],
    );
    expect(make).toHaveBeenCalledTimes(1);
    expect(database.db).toBe(made);
    expect(adapter.resolveSource).toHaveBeenLastCalledWith(other, { type: 'geojson' });
  });

  test('is made by the first source when the run sets up no workspace, and ended by its close', async () => {
    const database = runDatabase();
    const { adapter } = recording();

    const db = await database.handedTo(adapter).resolveSource(undefined, { type: 'geojson' });

    // A fresh autk-db database, as the grammar's data adapter makes its own.
    expect(mockMade).toHaveLength(1);
    expect(mockMade[0]).toBe(db);
    expect(database.db).toBe(db);
    database.close();
    expect(mockMade[0].db.terminate).toHaveBeenCalledTimes(1);
  });

  test('a run that loads no source makes none, and its close ends none', () => {
    const make = jest.fn();
    const database = runDatabase(make);
    database.handedTo(recording().adapter);

    database.close();

    expect(make).not.toHaveBeenCalled();
    expect(database.db).toBeUndefined();
  });
});

/**
 * The buildings tables a layer with `buildingsZeroHeight` draws (autk-grammar
 * 5.3.0), as the grammar's run hands them to its map: a part with no height
 * keeps no key of its height that holds no number.
 *
 * autk-map draws a part at its random 3 to 7 floors only when the part holds
 * none of `height`, `building:height`, `levels` and `building:levels`, the
 * building's keys merged with its part's own (`parts`). Curio hands such a part
 * on with none of them that holds no number (utils/autkInput
 * `withReadableHeights`), but the table the map reads back from autk-db can
 * hold them again: autk-db exports a table it keeps column by column with
 * every column on every feature, a part without a height as `height: null`,
 * and autk-map then leaves the part out. The run's database answers the map's
 * read of such a table without those keys (`withoutEmptyHeights`), as
 * `serveRaster` answers a raster's: the grammar's data adapter is wrapped,
 * never Autark.
 */
import { withoutEmptyHeights } from '../../utils/buildingHeight';
import { autkTableKey, autkWorkspaceOf } from './autkDataCompile';

/** Set on a database whose reads of those tables already drop the empty height keys. */
const ZERO_HEIGHTS = Symbol.for('curio.autk.zeroHeights');

/** *collection* with no key of a building's height that holds no number, on its features and their parts. */
function withoutEmptyBuildingHeights(collection: any): any {
    const features: any[] = Array.isArray(collection?.features) ? collection.features : [];
    let changed = false;
    const next = features.map((feature) => {
        const properties = withoutEmptyHeights(feature?.properties);
        if (properties === feature?.properties) return feature;
        changed = true;
        return { ...feature, properties };
    });
    return changed ? { ...collection, features: next } : collection;
}

/** Make *db* read each of *tables*, by key (`autkTableKey`), without the empty height keys; once a database. */
function readWithoutEmptyHeights(db: any, tables: ReadonlySet<string>): void {
    if (!db || typeof db.getLayer !== 'function' || db[ZERO_HEIGHTS]) return;
    const getLayer = db.getLayer.bind(db);
    db.getLayer = async (name: string, ...rest: any[]) => {
        const collection = await getLayer(name, ...rest);
        const workspace = typeof db.getCurrentWorkspace === 'function'
            ? autkWorkspaceOf({ workspace: db.getCurrentWorkspace() })
            : undefined;
        return tables.has(autkTableKey(workspace, name)) ? withoutEmptyBuildingHeights(collection) : collection;
    };
    db[ZERO_HEIGHTS] = true;
}

/**
 * Let one grammar instance hand its maps each of *tables*, the tables a layer
 * with `buildingsZeroHeight` draws (`zeroHeightTables`), without a key of a
 * building's height that holds no number: the database its data adapter loads
 * the sources into reads them so. Nothing for no table, or a grammar that keeps
 * no data adapter.
 */
export function withZeroHeightExports(grammar: any, tables: ReadonlySet<string>): void {
    const adapter = grammar?.dataAdapter;
    if (tables.size === 0 || !adapter || typeof adapter.resolveSource !== 'function') return;
    const resolveSource = adapter.resolveSource.bind(adapter);
    grammar.dataAdapter = {
        ...adapter,
        async resolveSource(db: any, source: any) {
            const target = await resolveSource(db, source);
            readWithoutEmptyHeights(target, tables);
            return target;
        },
    };
}

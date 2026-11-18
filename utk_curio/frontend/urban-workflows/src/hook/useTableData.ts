import { useFlowContext } from "../providers/FlowProvider";
import { ICodeDataContent, INodeData } from "../types";
import { useEffect, useRef, useState } from "react";
import { formatDate, mapTypes } from "../utils/formatters";
import { useProvenanceContext } from "../providers/ProvenanceProvider";
import { fetchData } from "../services/api";
import { sandboxArtifactId } from "../utils/flowOutputRef";
import { lazyRows } from "../utils/rowSource";
import { copyForFlags } from "../utils/poolFlagCopy";
import { keyedFramesAsOutputs } from "../utils/sandboxEnvelope";
import { RASTER_DATA_TYPE } from "../utils/raster/rasterWire";

/** A Python node's raster as the sandbox answers for it: its envelope's data is
 * the sandbox's file of it (`parseOutput`), where an Autark node's holds its cells. */
function isPythonRaster(value: any): boolean {
  return !!value && typeof value === "object" && value.dataType === RASTER_DATA_TYPE && typeof value.data === "string";
}

/** A reference to a raster: one that names its artifact and carries no data. */
function isRasterRef(value: any): boolean {
  return !!value && typeof value === "object" && value.dataType === RASTER_DATA_TYPE
    && value.data === undefined && sandboxArtifactId(value) !== null;
}

const useTableData = ({ data }: { data: INodeData }) => {
  const [tabData, setTabData] = useState<any[]>([]);
  const [activeTab, setActiveTab] = useState<string>("0");

  const dataInputBypass = useRef(false);
  const { workflowNameRef } = useFlowContext();
  const { nodeExecProv } = useProvenanceContext();

  useEffect(() => {
    if (dataInputBypass.current) {
      let startTime = formatDate(new Date());

      //data array error - James
      /*let typesInput: string[] = [];


            if (data.input != "") typesInput = data.input.dataType;

            let typesOuput: string[] = [...typesInput];
            */
      let typesInput: string[] = [];
      if (data.input && data.input.dataType) {
        typesInput = Array.isArray(data.input.dataType)
          ? data.input.dataType
          : [data.input.dataType];
      }
      let typesOuput: string[] = [...typesInput];
      //end data array error - James
      nodeExecProv(
        startTime,
        startTime,
        workflowNameRef.current,
        data.nodeId,
        mapTypes(typesInput),
        mapTypes(typesOuput),
        ""
      );
    }

    dataInputBypass.current = true;
  }, [data.input]);

  const createTableData = (parsedOutput: ICodeDataContent) => {
    // Lazy on purpose. DataPoolContent renders the 100-row preview from
    // /get-preview whenever it has one and falls back to this only when it
    // does not, so flattening the whole artifact here built 200k row objects
    // to display 100 of them. `lazyRows` builds a row when one is read: the
    // table's `rows.slice(0, maxRows)` costs a page, not an artifact.
    // @ts-ignore - parsedOutput is `any`-shaped through this hook
    return lazyRows(parsedOutput);
  };

  // `selectionEcho`: this run re-emits the same rows because of a selection
  // (another pool's propagation), so linked charts highlight rather than redraw.
  const processDataAsync = async (options?: { selectionEcho?: boolean }) => {
    try {
      // Normalize input wrappers: handle a bundle of several inputs
      let wrappers: any[] = [];
      if (data.input && typeof data.input === "object") {
        if (data.input.dataType === "outputs" && Array.isArray(data.input.data)) {
          wrappers = data.input.data;
        } else {
          wrappers = [data.input];
        }
      } else if (typeof data.input === "string" && data.input.trim()) {
        wrappers = [{ path: data.input.trim() }];
      }

      if (wrappers.length === 0) {
        setTabData([]);
        return { code: "success", content: "" };
      }

      // Known application-level shapes the rest of this hook handles directly.
      // Anything else (e.g. the sandbox's generic 'dict'/'list' envelope wrap on
      // a persisted artifact) is peeled until we reach one of these. A raster's
      // envelope is one: it is a tab of its own, as a layer is.
      const KNOWN_TYPES = new Set(["geodataframe", "dataframe", "outputs", RASTER_DATA_TYPE]);
      const unwrapToKnown = (v: any): any => {
        while (
          v && typeof v === "object" &&
          typeof v.dataType === "string" &&
          !KNOWN_TYPES.has(v.dataType) &&
          "data" in v
        ) {
          v = v.data;
        }
        return v;
      };

      // Expand multi-layer envelopes into one tab per layer. autk-grammar has
      // two emit shapes the pool must accept:
      //   - compute-only / data+compute: `layersToPoolWrapper` →
      //     `{dataType:'outputs', data:[{dataType:'geodataframe', data:FC, layerName, layerType}, ...]}`
      //   - data-only: `compileDataSpecToAutkDbJs` returns `[{name, type, geojson}, ...]`,
      //     then each raster table (a heatmap, a GeoTIFF) in its envelope, which
      //     the sandbox stores as `kind='list'`. After unwrap, the input is a
      //     plain JS array of those (each wrapped in `{dataType:'dict', data:{...}}`
      //     by parseOutput's list traversal).
      // Without expansion, `tabd = [theWholeWrapper]` and `createTableData`
      // has no branch for either → empty table. Normalise both shapes to
      // individual geodataframe entries so the downstream code stays uniform.
      // A raster among them keeps its envelope, in its place. A Python node's
      // raster (its data is the sandbox's file of it) names the artifact it
      // was read from and its part there, which is where a node after the pool
      // reads it (utils/grammarInput). An input that holds no table nor raster
      // of its own has no tabs.
      const tabsOf = (value: any, artifact: string | null): any[] => {
        const placed = (item: any, part: number) =>
          artifact && isPythonRaster(item) ? { ...item, artifact, part } : item;
        // A dict of frames is drawn as a tuple of them is: a tab per frame,
        // named after its key.
        const x = keyedFramesAsOutputs(value) ?? value;
        if (x == null) return [];
        if (x.dataType === 'outputs' && Array.isArray(x.data)) {
          return x.data.flatMap((item: any, part: number) => (item ? [placed(item, part)] : []));
        }
        if (Array.isArray(x)) {
          const tabs: any[] = [];
          x.forEach((item: any, part: number) => {
            if (!item) return;
            // parseOutput on a `list` recursively wraps each dict element
            // as `{dataType:'dict', data:{...}}`; peel any non-known envelope
            // until we reach the underlying layer record, or a raster.
            let rec: any = item;
            while (
              rec && typeof rec === 'object' &&
              typeof rec.dataType === 'string' &&
              !KNOWN_TYPES.has(rec.dataType) &&
              'data' in rec
            ) {
              rec = rec.data;
            }
            if (rec && rec.dataType === RASTER_DATA_TYPE) {
              tabs.push(placed(rec, part));
            } else if (rec && (rec.dataType === 'geodataframe' || rec.dataType === 'dataframe')) {
              // A Python list's frame, as a tuple's.
              tabs.push(rec);
            } else if (rec && rec.geojson?.type === 'FeatureCollection') {
              tabs.push({
                dataType: 'geodataframe',
                data: rec.geojson,
                layerName: rec.name,
                layerType: rec.type,
                // A table of another workspace than the default one stays in it.
                ...(typeof rec.workspace === 'string' && rec.workspace ? { workspace: rec.workspace } : {}),
              });
            }
          });
          return tabs;
        }
        return typeof x === 'object' && KNOWN_TYPES.has(x.dataType) ? [x] : [];
      };

      // The tabs of each input. One that names an artifact is fetched by its
      // filename or path, its generic envelopes unwrapped so the dataframe and
      // geodataframe processing below reads a recognized shape. One that
      // carries its content inline (no filename/path) — e.g. the safety-net
      // path in autk-grammar when the JS interpreter is unavailable — is read
      // as it is. A Python node's raster is not fetched: there are no rows in
      // it to show or flag, and the node it goes to reads it by its reference,
      // as the Autark node does (utils/grammarInput). It, and an input that
      // holds no table nor raster (a text, a number, a JSON list or dict), is
      // one tab, the reference it came as, with the type the store gives it,
      // and is handed on as that.
      const tabsByInput = await Promise.all(
        wrappers.map(async (w): Promise<any[]> => {
          if (isRasterRef(w)) return [w];
          const fileId = sandboxArtifactId(w);
          if (!fileId) {
            if (!w || typeof w !== 'object') return [];
            const tabs = tabsOf(w, null);
            return tabs.length > 0 || typeof w.dataType !== 'string' ? tabs : [w];
          }
          let raw: any;
          try {
            raw = await fetchData(fileId);
          } catch (err) {
            console.error("Fetch failed for", fileId, err);
            return [];
          }
          const known = unwrapToKnown(raw);
          const tabs = isPythonRaster(known) ? [] : tabsOf(known, fileId);
          if (tabs.length > 0) return tabs;
          const stored = typeof raw?.dataType === 'string' && raw.dataType ? { dataType: raw.dataType } : {};
          return [typeof w.dataType === 'string' && w.dataType ? w : { ...w, ...stored }];
        })
      );
      let tabd: any[] = tabsByInput.flat();

      // Drop layers with no rows/features. autk-db can hand the pool an empty
      // or null-feature layer (e.g. a PBF area with no parks); the
      // geodataframe branch below iterates `data.features`, which throws on
      // null ("can't access property Symbol.iterator"), and an empty layer
      // would otherwise show as a blank tab.
      tabd = tabd.filter((item: any) => {
        if (!item) return false;
        if (item.dataType === 'geodataframe') {
          return Array.isArray(item.data?.features) && item.data.features.length > 0;
        }
        if (item.dataType === 'dataframe') {
          const cols = item.data ? Object.keys(item.data) : [];
          return cols.length > 0 && Object.keys(item.data[cols[0]] ?? {}).length > 0;
        }
        return true;
      });

      tabd = tabd.map ((item) => {
        // The flags go on a copy: an inline input is the upstream node's own
        // object (utils/poolFlagCopy).
        const parsedInput = copyForFlags(item);
        if(parsedInput.dataType == "dataframe") {
          let columns = Object.keys(parsedInput.data);
          let dfIndices = Object.keys(parsedInput.data[columns[0]]);

          if (parsedInput.data.interacted == undefined) {
              parsedInput.data.interacted = {};

              for (const dfIndex of dfIndices) {
                  // initializing the interacted attribute
                  parsedInput.data.interacted[dfIndex] = "0";
              }
          }

          if (data.propagation != undefined) {
              // handling possible propagation of interaction from another pool
              let propagatedIndices = Object.keys(data.propagation).map(
                  (index: string) => {
                      return parseInt(index);
                  }
              );

              let interactedKeys = Object.keys(
                  parsedInput.data.interacted
              );

              for (let i = 0; i < interactedKeys.length; i++) {
                  let key = interactedKeys[i];

                  if (propagatedIndices.includes(i)) {
                      parsedInput.data.interacted[key] = data.propagation[i];
                  }
              }
          }
        }
        else if(parsedInput.dataType == "geodataframe") {
            for (const feature of parsedInput.data.features) {
                // initializing the interacted attribute
                feature.properties.interacted = "0";
            }

            if (data.propagation != undefined) {
                // handling possible propagation of interaction from another pool
                let propagatedIndices = Object.keys(data.propagation).map(
                    (index: string) => {
                        return parseInt(index);
                    }
                );

                for (let i = 0; i < parsedInput.data.features.length; i++) {
                    if (propagatedIndices.includes(i))
                        parsedInput.data.features[i].properties.interacted = data.propagation[i];
                }
            }
        }

        // Stringify the modified data for output
        // parsedInput.data = JSON.stringify(parsedInput.data);
        return parsedInput; // JSON.stringify(parsedInput);

      });

      // Build the downstream output exactly as the original DataPoolBox did:
      // send the fetched data object directly (no path attached) so downstream
      // boxes like the Autark node use the in-memory data rather than re-fetching from
      // the server and losing the initialised 'interacted' field.
      let callbackOutput: any;
      let contentOutput: any;

      // Layers read from one artifact, one or several, name it (`filename`): a
      // code node is sent that artifact (utils/flowOutputRef
      // `executionInputRef`), the one a run on the server hands it through the
      // pool. One layer an Autark node's list holds is built here, without it.
      const sourceIds = wrappers.map((w) => sandboxArtifactId(w));
      const inherited = data.input && typeof data.input === "object" && data.input.dataType === "outputs"
        && typeof data.input.filename === "string" && data.input.filename ? data.input.filename : null;
      const source = inherited ?? (sourceIds.length === 1 && sourceIds[0] ? sourceIds[0] : null);
      if (tabd.length === 1) {
        callbackOutput = source ? { ...tabd[0], filename: source } : tabd[0];
        contentOutput  = callbackOutput;    // object stored in output.content
      } else if (tabd.length > 1) {
        callbackOutput = { data: tabd, dataType: "outputs", ...(source ? { filename: source } : {}) };
        contentOutput  = { data: tabd, dataType: "outputs", ...(source ? { filename: source } : {}) };
      } else {
        callbackOutput = null;
        contentOutput  = '';
      }

      if (callbackOutput !== null && data.outputCallback) {
        data.outputCallback(data.nodeId, callbackOutput,
          options?.selectionEcho ? { selectionEcho: true } : undefined);
      }

      setTabData(tabd);

      return { code: "success", content: contentOutput };

    } catch (error) {
      setTabData([]);
      console.error("Error processing data asynchronously:", error);
      return { code: "error", content: error instanceof Error ? error.message : String(error) };
    }
  };

  return {
    createTableData,
    processDataAsync,
    setActiveTab,
    activeTab,
    tabData,
  };
};

export default useTableData;

import { GrammarAdapter, registerGrammarAdapter } from '../registry/grammarAdapter';
import { NodeType, ResolutionTypeUTK, VisInteractionType } from "../constants";
import { Environment, GrammarInterpreter } from "utk";
import { get_camera } from "../utils/parsing";
import { fetchData } from "../services/api";

Environment.serverless = true;

export const utkAdapter: GrammarAdapter = {
  grammarId: 'utk',
  validate: (spec) => true,

  render: async (container, spec, data, options) => {
    const input = data as any;
    const nodeId = (options as any)?.nodeId;
    const outputCallback = (options as any)?.outputCallback;
    const interactionsCallback = (options as any)?.interactionsCallback;
    console.log('utkAdapter.render called', {
    container,
    containerInDOM: document.body.contains(container),
    nodeId,
    hasOutputCallback: !!outputCallback,
    input: data,
  });
    // --- Parse input ---
    const errorMsg = "UTK box can only receive geodataframes";
    if (!input || input === "") throw new Error(errorMsg);

    if (input.dataType === "outputs") {
      for (const elem of input.data) {
        if (elem.dataType !== "geodataframe") throw new Error(errorMsg);
      }
    } else if (input.dataType !== "geodataframe") {
      throw new Error(errorMsg);
    }

    let geojsons;
    if (input.path) {
      geojsons = await fetchData(input.path);
    } else {
      geojsons = input;
    }

    geojsons = geojsons.dataType === "outputs"
      ? geojsons.data.map((e: any) => e.data)
      : [geojsons.data];

    for (const geojson of geojsons) {
      const parsed = typeof geojson === "string" ? JSON.parse(geojson) : geojson;
      if (!parsed.metadata?.name) throw new Error("All geojson layers for UTK must be named");
    }

    // --- toLayers ---
    const toLayersResponse = await fetch(
      process.env.BACKEND_URL + "/toLayers",
      {
        method: "POST",
        body: JSON.stringify({ geojsons }),
        headers: { "Content-type": "application/json; charset=UTF-8" },
      }
    );
    const json: any = await toLayersResponse.json();

    // --- Build grammar ---
    const generatedGrammar: any = {
      components: [{ id: "grammar_map", position: { width: [1, 12], height: [1, 4] } }],
      knots: [],
      ex_knots: [],
      grid: { width: 12, height: 4 },
      grammar: false,
    };

    let allCoordinates: number[] = [];

    for (let i = 0; i < json.layers.length; i++) {
      for (const geometry of json.layers[i].data) {
        allCoordinates = allCoordinates.concat(geometry.geometry.coordinates);
      }

      const layer = json.layers[i];
      let added = false;

      for (const joinedJson of json.joinedJsons) {
        if (joinedJson.id === layer.id) {
          for (let j = 0; j < joinedJson.incomingId.length; j++) {
            added = true;
            generatedGrammar.ex_knots.push({
              id: layer.id + j,
              out_name: layer.id,
              in_name: joinedJson.incomingId[j],
            });
          }
        }
      }

      if (!added) {
        generatedGrammar.ex_knots.push({ id: layer.id + "0", out_name: layer.id });
      }
    }

    const camera = get_camera(allCoordinates);
    const knotToLayerDict: any = {};

    const components = [{
      id: "grammar_map",
      json: {
        camera,
        knots: generatedGrammar.ex_knots.map((k: any) => {
          knotToLayerDict[k.id] = k.out_name;
          return k.id;
        }),
        interactions: generatedGrammar.ex_knots.map(() => ResolutionTypeUTK.NONE),
        widgets: [{ type: "TOGGLE_KNOT" }],
        grammar_type: "MAP",
      },
    }];

    // --- Compile grammar into container ---
    const specString = typeof spec === 'string' ? spec : JSON.stringify(spec);
    const useDefaultGrammar = !specString || specString === '{}';
    const grammarSpec = useDefaultGrammar
      ? JSON.stringify(generatedGrammar, null, 4)
      : specString;

    const parsed = JSON.parse(grammarSpec);
    if (!parsed.grid || !parsed.components || !parsed.knots) {
      console.warn("Grammar not ready yet, missing required fields");
      return;
    }

    // container.innerHTML = "";
    // container.style.width = "100%";
    // container.style.height = "100%";

    const mainDiv = document.createElement("div");
    mainDiv.style.width = "100%";
    mainDiv.style.height = "100%";
    container.appendChild(mainDiv);
    
    console.log('about to create GrammarInterpreter', {
  nodeId,
  parsed,
  mainDiv,
  layers: json.layers,
  joinedJsons: json.joinedJsons,
  components,
});
    new GrammarInterpreter(
    nodeId,        // ← from options, not data
    parsed,
    mainDiv,
    json.layers,
    json.joinedJsons,
    components as any,
    []
  );
    console.log('GrammarInterpreter created successfully');
outputCallback?.(nodeId, data);
console.log('outputCallback called');
    outputCallback?.(nodeId, data);
  },
};

registerGrammarAdapter(utkAdapter);
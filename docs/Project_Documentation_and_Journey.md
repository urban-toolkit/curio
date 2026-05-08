# Introduction & Disclaimer
## Intro & Background
For my course project, I aimed to "modify the data transfer between nodes in Curio to leverage Apache Arrow for data storage and DuckDB as a query engine". 
After 14 weeks of the course I had acheived what I had in mind for this goal, and that initial effort and modification can be seen in this ```main``` branch 
of this forked repository (the branch I am contributing to Curio). In week 14, a major modification to Curio was made that overlapped with my goal: DuckDB was implemented to handle file storage and
file management for Curio, replacing the temporary file storage strategy that involved storing files on disk in the folder **./.curio/data**. Using DuckDB as
for file storage as well was a goal I had for my version as well, but I wasn't able to get it working within the course timeline.

## Important Note
The ```feature/duck-db-and-arrow-transfer``` branch is my attempt at merging my initial effort of leveraging Arrow + DuckDB with Stefan's contribution of using DuckDB in Curio for file storage. **At present, 
the version of Curio implemented here does not function completely.** It works for some things, it has bugs for some other things (for more on this branch, see the docs/ folder of the forked repo after switching branches). 

## What is the Rest of this Markdown?
In the rest of this markdown, I document the main changes I made to Curio to add in the following:
1. Store .parquet files on-disk instead of .data files (still in the folder **./.curio/data**). This means we skip the serialization & compression steps done before and instead store files in-memory in columnar format.
2. Spin up a temporary, in-memory DuckDB instance to efficiently and directly query the .parquet files and retrieve the data in an Arrow Table.
3. Streaming the Arrow Table to the frontend instead of JSON. 

These changes span three pieces of Curio to do this: **Backend, Sandbox, and Frontend**. So, in the rest of this document, I'll go over the main additions and modifications!

# Installation & Setup
## Installation
For concreteness, I want to mention that on my system, I for some reason could not run it using Docker. I don't know why (I think it was a system issue, as I do have an older MacBook).
To run Curio (regardless of it was my version of the official version), I setup a Conda environment, following the steps under "Installing manually (with curio.py)" in the USAGE.md file inside the docs/ folder). 

## Setup
There is only one thing that needs to be added to get this implementation of Curio working. We need to install the ```apache-arrow``` library in the frontend so that
we can read the Arrow byte-stream being sent from the backend to the frontend. To do this, I do the following:
```
cd utk_curio/frontend/urban-workflows/
npm install apache-arrow
```

Other than this, I didn't need to install or add any packages and libraries manually; the ```requirements.txt``` installations handled the rest.

# Brief Overview of Changes
1. Store .parquet files on-disk instead of .data files (still in the folder **./.curio/data**). This means we skip the serialization & compression steps done before and instead store files in-memory in columnar format.
2. Spin up a temporary, in-memory DuckDB instance to efficiently and directly query the .parquet files and retrieve the data in an Arrow Table.
3. Streaming the Arrow Table to the frontend instead of JSON. 

These changes span three pieces of Curio to do this: **Backend, Sandbox, and Frontend**.

# Backend Changes
## ```app/api/routes.py```
TODO
TODO

# Sandbox Changes

## ```python_wrapper.txt```
The only change I needed to make in the Sandbox was to update this file so that .......
TODO

# Frontend Changes

## ```hook/useVega.ts```
In this file, we update the ```parseInputData``` function so that we can intercept the Arrow byte-stream in the ```services/api.ts``` file, and clean it properly so that
when it is passed to Vega-Lite nodes it has extracted the rows and done any necessary conversions (nearly the same change is done in ```adapters/useVegaAdapter.ts``` as well, which is documented below).

```
const parseInputData = async (input: any) => {
    let values: any = [];
    let parsedInput = data.input; //JSON.parse(data.input);
    if (parsedInput == "" || parsedInput == null || parsedInput == undefined) {
      return [];
    }

    let inputType = parsedInput.dataType; // JSON.parse(data.input)["dataType"];

    if (inputType != "dataframe" && inputType !== "geodataframe") {
      throw new Error(inputType + " is not a valid input type for the 2D Plot (Vega-Lite)");
    }

    const parserMap = {
      "dataframe": parseDataframe,
      "geodataframe": parseGeoDataframe,
    };

    const isDataPath = typeof parsedInput.data === 'string';
    const pathToFetch = isDataPath ? parsedInput.data : parsedInput.path;

    if (pathToFetch) {
      // Pass 'true' so the Arrow IPC parses directly to an array of row objects
      let fetched = await fetchData(pathToFetch, true);
      
      // If Arrow handled it, it's already perfectly formatted for Vega
      if (Array.isArray(fetched)) {
        values = fetched;
      } else {
        // Fallback for legacy JSON
        const parser = parserMap[parsedInput.dataType as keyof typeof parserMap];
        if (parser) values = parser(fetched.data !== undefined ? fetched.data : fetched);
      }
    } else {
      // Fallback for legacy inline JSON
      const parser = parserMap[parsedInput.dataType as keyof typeof parserMap];
      if (parser) values = parser(parsedInput.data);
    }

    return values;
```

## ```adapters/vegaLiteAdapter.ts```
In this file, we update the ```parseInputData``` function so that we can intercept the Arrow byte-stream in the ```services/api.ts``` file, and clean it properly so that
when it is passed to Vega-Lite nodes it has extracted the rows and done any necessary conversions.
```
async function parseInputData(input: any): Promise<any[]> {
  if (!input || input === '') {
    throw new Error('Input data must be provided');
  }

  const inputType = input.dataType;
  if (inputType !== 'dataframe' && inputType !== 'geodataframe') {
    throw new Error(`${inputType} is not a valid input type for Vega-Lite`);
  }

  const parserMap: Record<string, (data: any) => any> = {
    dataframe: parseDataframe,
    geodataframe: parseGeoDataframe,
  };

  const isDataPath = typeof input.data === 'string';
  const pathToFetch = isDataPath ? input.data : input.path;

  if (pathToFetch) {
    // Pass 'true' so the Arrow IPC parses directly to an array of row objects
    const fetched = await fetchData(pathToFetch, true);
    
    if (Array.isArray(fetched)) return fetched;

    // Fallback for legacy JSON
    const parser = parserMap[inputType];
    return parser ? parser(fetched.data !== undefined ? fetched.data : fetched) : [];
  }

  // Fallback for legacy inline JSON
  const parser = parserMap[inputType];
  return parser ? parser(input.data) : [];
}
```

## ```adapters/node/DataPoolLifecycle.tsx```
The Data Pool node is crucial in Curio workflows, and it displays and passes data through to downstream nodes often. We had to make numerous updates around this file to ensure
the Arrow data was being passed to downstream nodes properly and displayed in the frontend. Each change is serparately and briefly described below.

The first ```useEffect``` is changed so that we construct an ICodeData object (consisting of the code string and content payload), as the output state variable expects this. 
```
useEffect(() => {
    let cancelled = false;
    const loadData = async () => {
      const result = await processDataAsync();
      if (!cancelled && data.input) {
        // Wrap the input in the expected ICodeData structure
        setOutput({ code: "success", content: data.input });
        
        // Pass the input directly, as it is already the content payload
        data.outputCallback(data.nodeId, data.input);
      }
    };
    loadData();
    return () => { cancelled = true; };
  }, [data.input, data.newPropagation]);
```

In the second ```UseEffect```, we add a conditional to skip the interaction logic that is needed to iterate over the JSON that was originally being passed through. Since the payload 
is now a Paqrquet file path, we want to return early as we can't loop over it as if it were JSON. 
```
useEffect(() => {
    if (output.content != "" && data.interactions != undefined) {

      let parsedInput: ICodeDataContent;
      if (typeof output.content === 'object' && (output.content as any).dataType === 'outputs') {
        parsedInput = (output.content as any).data[0];
      } else {
        parsedInput = output.content as ICodeDataContent;
      }

      // Bypass legacy JSON interaction logic for Parquet paths
      if (!parsedInput || !parsedInput.data || typeof parsedInput.data === 'string') {
          return;
      }

      let interactedIndices: any = []; // between visualizations
      
      // ... the rest of the interaction logic is the same
```

The final change in this file is to the ```tableData``` memo to decouple the UI from the output state when displaying data.
```
 const tableData = useMemo(() => {
    // 'output' now holds the Parquet path, so we use 'tabData' (populated by processDataAsync) for rendering the UI.
    const displayTable = tabData[parseInt(activeTab)];
    if (displayTable) return createTableData(displayTable as ICodeDataContent);
    return [];
  }, [tabData, activeTab, createTableData]);
```

## ```services/api.ts```
In this file, the first thing we needed to do was update the ```headers``` so that we would accept the Arrow byte-stream as well:
```
headers: {
                // Change Content-Type to Accept (which tells the server what we want to receive)
                'Accept': 'application/vnd.apache.arrow.stream, application/json',
            },
```

The full ```fetchData``` function now looks as below. The first thing we needed to do was update the ```headers``` so that we would accept the Arrow byte-stream as well.
After this we add conditionals to intercept the Arrow byte-stream being sent so that we can use it (pass data between nodes for cleaning, transformation, etc.) and display it
(in a table or plot). To do this, we use the ```tableFromIPC``` function from the ```apache-arrow``` library. 

Since vega-lite expects row-oriented data, we transform the columnar format to row format and ensure they are proper type (casting BigInt to Number to avoid crashes, which we do
for the columnar data too). 

```
import { tableFromIPC } from 'apache-arrow';

export async function fetchData(fileName: string, vega: boolean = false) {
    try {
        // We request the file without the vega URL param because 
        // the backend now streams the raw Arrow IPC format directly.
        const url = `${process.env.BACKEND_URL}/get?fileName=${encodeURIComponent(fileName)}`;
        console.log(`Fetching ${url}`);
        
        const response = await fetch(url, {
            headers: {
                // Change Content-Type (which is for sending data) 
                // to Accept (which tells the server what we want to receive)
                'Accept': 'application/vnd.apache.arrow.stream, application/json',
            },
        });

        if (!response.ok) {
            throw new Error(`Failed to fetch file ${url}: ${response.statusText}`);
        }

        const contentType = response.headers.get('content-type');

        // ARROW BYTE-STREAM PATH
        if (contentType && contentType.includes('application/vnd.apache.arrow.stream')) {
            const arrayBuffer = await response.arrayBuffer();
            const arrowTable = tableFromIPC(arrayBuffer);

            if (vega) {
                // Vega-Lite expects row-oriented data
                const vegaData = arrowTable.toArray().map(row => {
                    const obj = row?.toJSON();
                    // FIX: Vega-Lite crashes on BigInts. Cast them to standard Numbers.
                    for (const key in obj) {
                        if (typeof obj[key] === 'bigint') {
                            obj[key] = Number(obj[key]);
                        }
                    }
                    return obj;
                });
                return vegaData;
            }

            // Existing Curio nodes expect a column-oriented dictionary.
            const columnsData: Record<string, any[]> = {};
            arrowTable.schema.fields.forEach(field => {
                const column = arrowTable.getChild(field.name);
                if (column) {
                    const arr = Array.from(column.toArray());
                    // Cast BigInts to standard Numbers for frontend Data Pools
                    columnsData[field.name] = arr.map(v => typeof v === 'bigint' ? Number(v) : v);
                } else {
                    columnsData[field.name] = [];
                }
            });

            const reconstructedJson = {
                data: columnsData,
                dataType: "dataframe"
            };

            console.log(`Fetched Arrow stream`, reconstructedJson);
            return reconstructedJson;
        }

        // LEGACY JSON PATH (Metadata, Configs, Old Files)
        const jsonData = await response.json();

        if (vega) {
            return transformToVega(jsonData);
        }

        console.log(`Fetched JSON data`, jsonData);
        return jsonData;

    } catch (error: unknown) {
        console.error("Error:", error instanceof Error ? error.message : String(error));
        throw error;
    }
}
```

# Concluding Notes

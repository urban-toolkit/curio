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
For this file, we update the way it checks the input type because the input may now be a GeoDataframe/Dataframe. The code of ```if input:``` that was here before will try and do a
True/False check on our Dataframe, and this will cause an ambiguity error (something like "The truth value of a DataFrame is ambiguous.")! Due to this, we have to use the ```isinstance``` function to check what we are working with. If it is a Dataframe, we skip the dictionary parsing that was done previously.

```
# Use type-checking first to safely short-circuit the boolean evaluation of DataFrames
if isinstance(input, (pd.DataFrame, gpd.GeoDataFrame)) or input:
    checkIOType(input, nodeType)
    if(dataType == 'outputs'):
        incomingInput = []
        for elem in input:
            # Bypass the legacy dict parser if the element is already a DataFrame
            if isinstance(elem, (pd.DataFrame, gpd.GeoDataFrame)):
                incomingInput.append(elem)
            else:
                incomingInput.append(parseInput(elem))
    else:
        # Bypass the legacy dict parser if the input is already a DataFrame
        if isinstance(input, (pd.DataFrame, gpd.GeoDataFrame)):
            incomingInput = input
        else:
            incomingInput = parseInput(input)
else:
    incomingInput = ''
```

## ```util/parsers.py```
For this file, we had to make serveral changes to functions to ensure we were storing files in Parquet format where possible and loading, reading, and passing this data right.

In the ```check_dataframe_input``` function, we updated it to accept and pass through any raw Dataframe objects, The raw Dataframe is what we now return when we read the .parquet files, so we don't want to do ```data.get('dataType)``` on these as this will mistakenly try to access a column named 'dataType'. 
```
def check_dataframe_input(data, nodeType):
    if isinstance(data, list):
        return
        
    # NEW: If it is already a raw DataFrame, it is valid!
    if isinstance(data, (pd.DataFrame, gpd.GeoDataFrame)):
        return 

    # Legacy dictionary checks
    if data.get('dataType') == 'outputs' and len(data.get('data', [])) > 5:
        raise Exception(f'{nodeType} only supports five inputs')

    valid_types = {'dataframe', 'geodataframe'}
    if data.get('dataType') == 'outputs':
        for elem in data.get('data', []):
            if elem.get('dataType') not in valid_types:
                raise Exception(f'{nodeType} only supports DataFrame and GeoDataFrame as input')
    elif data.get('dataType') not in valid_types:
        raise Exception(f'{nodeType} only supports DataFrame and GeoDataFrame as input')
```

For the same reason as above, we updated the ```checck_transformation_input``` function to also accept raw DataFrame or Raster objects.
```
def check_transformation_input(data, nodeType):
    if isinstance(data, list):
        return
        
    # NEW: If it is already a raw DataFrame or Raster, it is valid!
    if isinstance(data, (pd.DataFrame, gpd.GeoDataFrame)):
        return 
    if isinstance(data, rasterio.io.DatasetReader):
        return

    # Legacy dictionary checks
    valid_types = {'dataframe', 'geodataframe', 'raster'}
    if data.get('dataType') == 'outputs' and len(data.get('data', [])) > 2:
        raise Exception(f'{nodeType} only supports one or two inputs')

    if data.get('dataType') == 'outputs':
        for elem in data.get('data', []):
            if elem.get('dataType') not in valid_types:
                raise Exception(f'{nodeType} only supports DataFrame, GeoDataFrame, and Raster as input')
    elif data.get('dataType') not in valid_types:
        raise Exception(f'{nodeType} only supports DataFrame, GeoDataFrame, and Raster as input')
```

One of the main changes for our Curio project was saving the data in .parquet files so we get on-disk, in-memory columnar storage. To do this, we update the ```save_memory_mapped_file``` function to save tabular data to .parquet files instead of .data files. 
```
def save_memory_mapped_file(data):
    """
    Saves tabular data as a Parquet file and nested dicts as standard JSON.

    Args:
        data (dict | pd.DataFrame): The data to be saved.

    Returns:
        str: The relative path of the saved file.
    """
    launch_dir = Path(os.environ.get("CURIO_LAUNCH_CWD", os.getcwd())).resolve()
    shared_disk_path = os.environ.get("CURIO_SHARED_DATA", "./.curio/data/")
    save_dir = (launch_dir / shared_disk_path).resolve()
    
    # Ensure the directory exists
    os.makedirs(save_dir, exist_ok=True)

    timestamp = str(int(time.time()))

    # Extract the actual payload from the wrapper dictionary
    payload = data.get('data') if isinstance(data, dict) and 'data' in data else data

    # 1. PARQUET EXPORT: If payload is tabular, save it as Parquet
    if isinstance(payload, (pd.DataFrame, gpd.GeoDataFrame)):
        unique_filename = f"{timestamp}_output.parquet"
        full_path = save_dir / unique_filename
        
        try:
            # Attempt to save the DataFrame to Parquet natively
            payload.to_parquet(full_path, engine='pyarrow', index=False)
        except Exception as e:
            # Fallback: PyArrow strictly enforces column types.
            # If a user's code mixes types (like putting a 0 in a string column),
            # we coerce all object columns to strings so the system doesn't crash.
            for col in payload.select_dtypes(include=['object']).columns:
                payload[col] = payload[col].astype(str)
                
            # Try saving again
            payload.to_parquet(full_path, engine='pyarrow', index=False)

    # 2. JSON EXPORT: If data is a dict (metadata, vega specs), save as JSON
    elif isinstance(data, dict):
        json_bytes_initial = json.dumps(data, ensure_ascii=False).encode('utf-8')
        input_hash = hashlib.sha256(json_bytes_initial[:1024]).digest()[:4].hex()
        unique_filename = f"{timestamp}_{input_hash[:25]}.json"
        # Inject the filename into the data
        data['filename'] = unique_filename
        full_path = save_dir / unique_filename
        
        with open(full_path, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False)
            
    else:
        raise TypeError("Unsupported data type. Must be a Pandas DataFrame or dict.")

    relative_path = full_path.relative_to(shared_disk_path)
    return str(relative_path).replace("\\", "/")
```

Since we now store files in Parquet form, we need to ensure we update the ```load_memory_mapped_file``` function so that when it encounters a .parquet file it properly reads it
back into a Dataframe.
```
def load_memory_mapped_file(file_path):
    """
    Loads data from Parquet, JSON, or legacy compressed data files.

    Args:
        file_path (str): The path of the file to load.

    Returns:
        dict | pd.DataFrame: The loaded data.
    """
    launch_dir = Path(os.environ.get("CURIO_LAUNCH_CWD", os.getcwd())).resolve()
    shared_disk_path = os.environ.get("CURIO_SHARED_DATA", "./.curio/data/")
    lod_dir = (launch_dir / shared_disk_path).resolve()

    requested_path = Path(file_path)
    full_path = (lod_dir / requested_path).resolve()

    # Security check to prevent directory traversal
    if not str(full_path).startswith(str(lod_dir)):
        raise PermissionError(f"Access to path '{full_path}' is not allowed.")

    if not full_path.exists():
        raise FileNotFoundError(f"The file {full_path} does not exist.")

    # 1. LOAD PARQUET
    if full_path.suffix == '.parquet':
        # Instantly reads the columnar data back into a DataFrame
        return pd.read_parquet(full_path, engine='pyarrow')
        
    # 2. LOAD STANDARD JSON
    elif full_path.suffix == '.json':
        with open(full_path, "r", encoding="utf-8") as file:
            return json.load(file)
            
    # 3. LOAD LEGACY COMPRESSED DATA
    else:
        with open(full_path, "rb") as file:
            with mmap.mmap(file.fileno(), 0, access=mmap.ACCESS_READ) as mmapped_file:
                decompressed_data = zlib.decompress(mmapped_file[:])
                return json.loads(decompressed_data.decode('utf-8'))
```

Lastly for the ```parsers.py``` file, we update the ```parseOutput``` function so that we keep the Dataframe and GeoDataframe objects as they are, without converting them
to a dictionary of GeoJSON string (as was done before).
```
# Output Functions
def parseOutput(output):
    json_output = {'data': '', 'dataType': ''}
    if isinstance(output, (int, float, bool, str)):
        json_output['data'] = output
        json_output['dataType'] = type(output).__name__
    elif isinstance(output, list):
        json_output['data'] = [parseOutput(elem) for elem in output]
        json_output['dataType'] = type(output).__name__
    elif isinstance(output, dict):
        json_output['data'] = output
        json_output['dataType'] = type(output).__name__
    elif isinstance(output, pd.DataFrame) and not isinstance(output, gpd.GeoDataFrame):
        # Keep the raw DataFrame object instead of converting to a dict
        json_output['data'] = output
        json_output['dataType'] = 'dataframe'
    elif isinstance(output, gpd.GeoDataFrame):
        # Keep the raw GeoDataFrame object instead of converting to a GeoJSON string
        json_output['data'] = output
        json_output['dataType'] = 'geodataframe'
        
        # Preserve metadata if it exists
        if hasattr(output, 'metadata') and 'name' in output.metadata:
            json_output['metadata'] = {'name': output.metadata['name']}
    elif isinstance(output, rasterio.io.DatasetReader):
        json_output['data'] = output.name
        json_output['dataType'] = 'raster'
    elif isinstance(output, tuple):
        json_output['data'] = [parseOutput(elem) for elem in output]
        json_output['dataType'] = 'outputs'

    return json_output
```

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

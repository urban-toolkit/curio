import { IPropagation, useFlowContext } from "../providers/FlowProvider";
import { BoxType, ResolutionType, VisInteractionType } from "../constants";
import { ICodeDataContent, ICodeData, INodeData, INode } from "../types";
import { useEffect, useRef, useState } from "react";
import { formatDate, mapTypes } from "../utils/formatters";
import { useProvenanceContext } from "../providers/ProvenanceProvider";
import { fetchData } from "../services/api";

const useTableData = ({ data }: { data: INodeData }) => {
  const [resolutionMode, setResolutionMode] = useState<string>(ResolutionType.OVERWRITE);// how interaction conflicts between plots are resolved
  const [plotResolutionMode, setPlotResolutionMode] = useState<string>(ResolutionType.OVERWRITE);// how interaction conflicts are solved in the context of one plot
  const [tabData, setTabData] = useState<any[]>([]);
  const [activeTab, setActiveTab] = useState<string>("0");

  useEffect(() => {
    const selectBetween = document.getElementById(
      data.nodeId + "_" + "select_between"
    ) as HTMLElement;

    selectBetween.addEventListener("change", (event) => {
      if (event.target != null) {
        let target = event.target as HTMLOptionElement;
        const selectedOption = target.value;
        setResolutionMode(selectedOption);
      }
    });

    const selectIntra = document.getElementById(data.nodeId + "_" + "select_intra") as HTMLElement;

    selectIntra.addEventListener("change", (event) => {
      if (event.target != null) {
        let target = event.target as HTMLOptionElement;
        const selectedOption = target.value;
        setPlotResolutionMode(selectedOption);
      }
    });
  }, []);

  const dataInputBypass = useRef(false);
  const { workflowNameRef } = useFlowContext();
  const { boxExecProv } = useProvenanceContext();
  useEffect(() => {
    if (dataInputBypass.current) {
      let startTime = formatDate(new Date());

      //data array error - James
      /*let typesInput: string[] = [];


            if (data.input != "") typesInput = data.input.dataType;//getType([data.input]);

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
      boxExecProv(
        startTime,
        startTime,
        workflowNameRef.current,
        BoxType.DATA_POOL + "-" + data.nodeId,
        mapTypes(typesInput),
        mapTypes(typesOuput),
        ""
      );
    }

    dataInputBypass.current = true;
  }, [data.input]);

  const createTableData = (parsedOutput: ICodeDataContent) => {
    let tableData = [];

    if (parsedOutput.dataType == "dataframe") {
      let columns = Object.keys(parsedOutput.data);
      let dfIndices = Object.keys(parsedOutput.data[columns[0]]);

      for (let i = 0; i < dfIndices.length; i++) {
        let element: any = {};

        for (const column of columns) {
          element[column] = parsedOutput.data[column][dfIndices[i]];
        }

        tableData.push(element);
      }
    } else if (
      parsedOutput.dataType == "geodataframe" &&
      parsedOutput.data.features.length > 0
    ) {
      let columns = Object.keys(parsedOutput.data.features[0].properties);

      for (let i = 0; i < parsedOutput.data.features.length; i++) {
        let element: any = {};

        for (const column of columns) {
          element[column] = parsedOutput.data.features[i].properties[column];
        }

        tableData.push(element);
      }
    }

    return tableData;
  };

  const parseInputData = ({
      input: newInput,
      ...data
    }: {
      input: string;
      propagation: [IPropagation];
    }
  ) => {
    if (newInput != "") {
      // including interacted tag
      let parsedInput = JSON.parse(newInput);

      parsedInput.data = JSON.parse(parsedInput.data);

      if (parsedInput.dataType == "dataframe") {
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
          let propagatedIndices = Object.keys(data.propagation).map((index: string) => {
            return parseInt(index);
          });

          let interactedKeys = Object.keys(parsedInput.data.interacted);

          for (let i = 0; i < interactedKeys.length; i++) {
            let key = interactedKeys[i];

            if (propagatedIndices.includes(i)) {
              const { propagation } = data;
              parsedInput.data.interacted[key] = propagation[i];
            }
          }
        }
      } else if (parsedInput.dataType == "geodataframe") {
        for (const feature of parsedInput.data.features) {
          // initializing the interacted attribute
          feature.properties.interacted = "0";
        }

        if (data.propagation != undefined) {
          // handling possible propagation of interaction from another pool
          let propagatedIndices = Object.keys(data.propagation).map((index: string) => {
            return parseInt(index);
          });

          for (let i = 0; i < parsedInput.data.features.length; i++) {
            if (propagatedIndices.includes(i))
              parsedInput.data.features[i].properties.interacted = data.propagation[i];
          }
        }
      }

      parsedInput.data = JSON.stringify(parsedInput.data);
      newInput = JSON.stringify(parsedInput);
    }

    return newInput;
  };

  const parseOutputData = ({ output }: { output: ICodeData; }
  ) => {
    if (output.content == "" || data.interactions === undefined) {
      return { newOutput: output.content, propagationObj: undefined };
    }

    let parsedInput: ICodeDataContent = output.content as ICodeDataContent;
    // let propagationObj: Partial<IPropagation> = {
    //   nodeId: data.nodeId,
    //   propagation: {},
    // };
    //
    // if (output.content != "") {
    //   let parsedInput = JSON.parse(<string>data.input);
    //   parsedInput.data = JSON.parse(parsedInput.data);

    let interactedIndices: any = []; // between visualizations

    let columns: string[] = [];
    let dfIndices: string[] = [];

    if (parsedInput.dataType == "dataframe") {
      columns = Object.keys(parsedInput.data);
      dfIndices = Object.keys(parsedInput.data[columns[0]]);
    }

    for (const interaction of data.interactions) {
      let localInteractedIndices: any = [];

      let details = interaction.details;

      let selects = Object.keys(details);

      for (const select of selects) {
        if (details[select].source == BoxType.VIS_UTK) {
          // interactions from UTK only affect matching named geodataframes
          if (parsedInput.data.metadata == undefined) {
            continue;
          }

          if (parsedInput.data.metadata.name == undefined) {
            continue;
          }

          if (parsedInput.data.metadata.name != select) {
            continue;
          }
        }

        if (details[select].type == VisInteractionType.POINT) {
          // solve point interaction
          localInteractedIndices.push({
            priority: details[select].priority,
            indices: details[select].data.map((index: number) => {
              return index;
            }),
          });
        } else if (details[select].type == VisInteractionType.INTERVAL) {
          // solve interval (brushing) interaction
          let brushedColumns = Object.keys(details[select].data);

          let interactedObj: {
            priority: number;
            indices: number[];
          } = {
            priority: details[select].priority,
            indices: [],
          };

          let objectsCounter = 0;

          if (parsedInput.dataType == "dataframe") objectsCounter = dfIndices.length;
          else if (parsedInput.dataType == "geodataframe")
            objectsCounter = parsedInput.data.features.length;

          for (let i = 0; i < objectsCounter; i++) {
            let interacted = true;

            for (const brushedColumn of brushedColumns) {
              let brushBoundaries = details[select].data[brushedColumn];

              if (brushBoundaries.length > 0 && typeof brushBoundaries[0] == "string") {
                // categorial or ordinal variable

                if (parsedInput.dataType == "dataframe") {
                  if (!brushBoundaries.includes(parsedInput.data[brushedColumn][dfIndices[i]])) {
                    interacted = false;
                    break;
                  }
                } else if (parsedInput.dataType == "geodataframe") {
                  if (
                    !brushBoundaries.includes(
                      parsedInput.data.features[i].properties[brushedColumn]
                    )
                  ) {
                    interacted = false;
                    break;
                  }
                }
              } else if (brushBoundaries.length == 2) {
                // numerical interval

                let value = -1;

                if (parsedInput.dataType == "dataframe") {
                  value = parsedInput.data[brushedColumn][dfIndices[i]];
                } else if (parsedInput.dataType == "geodataframe") {
                  value = parsedInput.data.features[i].properties[brushedColumn];
                }

                if (value < brushBoundaries[0] || value > brushBoundaries[1]) {
                  interacted = false;
                  break;
                }
              }
            }

            if (brushedColumns.length == 0) {
              interacted = false;
            }

            if (interacted) {
              interactedObj.indices.push(i);
            }
          }

          localInteractedIndices.push(interactedObj);
        } else if (details[select].type == VisInteractionType.UNDETERMINED) {
          localInteractedIndices.push({
            priority: details[select].priority,
            indices: [],
          });
        }
      }

      let interactedList: number[] = [];

      if (plotResolutionMode == ResolutionType.OVERWRITE) {
        for (const elem of localInteractedIndices) {
          // using the interactions of the plot with higher priority
          if (elem.priority == 1) {
            interactedList = [...elem.indices];
          }
        }
      } else if (plotResolutionMode == ResolutionType.MERGE_AND) {
        let allArrays = localInteractedIndices.map((elem: any) => {
          return [...elem.indices];
        });

        if (allArrays.length > 0)
          interactedList = allArrays.reduce((a: number[], b: number[]) =>
            a.filter((c) => b.includes(c))
          ); // index is only include if it was interacted in all plots
      } else if (plotResolutionMode == ResolutionType.MERGE_OR) {
        let auxSet = new Set();

        for (const elem of localInteractedIndices) {
          // using the interactions of the plot with higher priority
          for (const value of elem.indices) {
            auxSet.add(value);
          }
        }

        interactedList = Array.from(auxSet) as number[];
      }

      interactedIndices.push({
        priority: interaction.priority,
        indices: [...interactedList],
      });
    }

    let interactedList: number[] = [];

    if (resolutionMode == ResolutionType.OVERWRITE) {
      for (const elem of interactedIndices) {
        // using the interactions of the plot with higher priority
        if (elem.priority == 1) {
          interactedList = [...elem.indices];
        }
      }
    } else if (resolutionMode == ResolutionType.MERGE_AND) {
      let allArrays = interactedIndices.map((elem: any) => {
        return [...elem.indices];
      });

      if (allArrays.length > 0)
        interactedList = allArrays.reduce((a: number[], b: number[]) =>
          a.filter((c) => b.includes(c))
        ); // index is only include if it was interacted in all plots
    } else if (resolutionMode == ResolutionType.MERGE_OR) {
      let auxSet = new Set();

      for (const elem of interactedIndices) {
        // using the interactions of the plot with higher priority
        for (const value of elem.indices) {
          auxSet.add(value);
        }
      }

      interactedList = Array.from(auxSet) as number[];
    }

    parsedInput.data.interacted = {};

    let propagationObj: IPropagation = {
      nodeId: data.nodeId,
      propagation: {},
    };

    let objectsCounter = 0;

    let buildingsLayer = false;

    if (
      parsedInput.data.features != undefined &&
      parsedInput.data.features.length > 0 &&
      parsedInput.data.features[0].properties.building_id != undefined
    )
      buildingsLayer = true;

    if (parsedInput.dataType == "dataframe") objectsCounter = dfIndices.length;
    else if (parsedInput.dataType == "geodataframe")
      objectsCounter = parsedInput.data.features.length;

    if (!buildingsLayer) {
      for (let i = 0; i < objectsCounter; i++) {
        // console.log(interactedList);
        if (interactedList.includes(i)) {
          if (parsedInput.dataType == "dataframe") {
            parsedInput.data.interacted[dfIndices[i]] = "1"; // 1 -> interacted with

            if (parsedInput.data.linked != undefined) {
              for (const index of parsedInput.data.linked[dfIndices[i]]) {
                propagationObj.propagation[index] = "1";
              }
            }
          } else if (parsedInput.dataType == "geodataframe") {
            parsedInput.data.features[i].properties.interacted = "1"; // 1 -> interacted with
            if (parsedInput.data.features[i].properties.linked != undefined) {
              for (const index of parsedInput.data.features[i].properties.linked) {
                propagationObj.propagation[index] = "1";
              }
            }
          }
        } else {
          if (parsedInput.dataType == "dataframe") {
            parsedInput.data.interacted[dfIndices[i]] = "0"; // 0 -> not interacted with
            if (parsedInput.data.linked != undefined) {
              for (const index of parsedInput.data.linked[dfIndices[i]]) {
                propagationObj.propagation[index] = "0";
              }
            }
          } else if (parsedInput.dataType == "geodataframe") {
            parsedInput.data.features[i].properties.interacted = "0"; // 0 -> not interacted with
            if (parsedInput.data.features[i].properties.linked != undefined) {
              for (const index of parsedInput.data.features[i].properties.linked) {
                propagationObj.propagation[index] = "0";
              }
            }
          }
        }
      }
    } else {
      let currentBuildingId = -1;
      let uniqueBuildingIndex = -1;

      for (const feature of parsedInput.data.features) {
        if (feature.properties.building_id != currentBuildingId) {
          currentBuildingId = feature.properties.building_id;
          uniqueBuildingIndex += 1;
        }

        if (interactedList.includes(uniqueBuildingIndex)) {
          feature.properties.interacted = "1"; // 1 -> interacted with
        } else {
          feature.properties.interacted = "0"; // 0 -> not interacted with
        }
      }
    }

    // parsedInput.data = JSON.stringify(parsedInput.data);
    // let newOutput = JSON.stringify(parsedInput); // new output after applying interactions
    // parsedInput.data = parsedInput.data;
    let newOutput = parsedInput; // new output after applying interactions

    return { newOutput, propagationObj };
  };

  const customWidgetsCallback = (div: HTMLElement) => {
    const labelBetween = document.createElement("label");
    labelBetween.setAttribute("for", "betweenPlot");
    labelBetween.style.marginRight = "5px";
    labelBetween.textContent = "Conflict between visualizations: ";

    const selectBetween = document.createElement("select");
    selectBetween.setAttribute("name", "betweenPlot");
    selectBetween.setAttribute("id", data.nodeId + "_select_between");

    ["Overwrite", "Merge (AND)", "Merge (OR)"].forEach((optionText) => {
      const option = document.createElement("option");
      option.setAttribute("value", optionText.toUpperCase().replace(/\s/g, "_"));
      option.textContent = optionText;
      selectBetween.appendChild(option);
    });

    const br = document.createElement("br");

    const labelIntra = document.createElement("label");
    labelIntra.setAttribute("for", "intraPlots");
    labelIntra.style.marginRight = "5px";
    labelIntra.textContent = "Conflict inside visualization: ";

    const selectIntra = document.createElement("select");
    selectIntra.setAttribute("name", "intraPlots");
    selectIntra.setAttribute("id", data.nodeId + "_select_intra");

    ["Overwrite", "Merge (AND)", "Merge (OR)"].forEach((optionText) => {
      const option = document.createElement("option");
      option.setAttribute("value", optionText.toUpperCase().replace(/\s/g, "_"));
      option.textContent = optionText;
      selectIntra.appendChild(option);
    });

    div.appendChild(labelBetween);
    div.appendChild(selectBetween);
    div.appendChild(br);
    div.appendChild(labelIntra);
    div.appendChild(selectIntra);
  };

  const processDataAsync = async () => {
    try {
      // Normalize input wrappers: handle merge outputs
      let wrappers: any[] = [];
      if (data.input && typeof data.input === "object") {
        if (data.input.dataType === "outputs" && Array.isArray(data.input.data)) {
          wrappers = data.input.data;
        } else {
          wrappers = [data.input];
        }
      }

      // Fetch each wrapper by filename or path
      const fetched = await Promise.all(
        wrappers.map(async (w) => {
          const fileId = w.filename ?? w.path;
          if (!fileId) return null;
          try {
            return await fetchData(fileId);
          } catch (err) {
            console.error("Fetch failed for", fileId, err);
            return null;
          }
        })
      );

      // Filter out nulls
      const tabd = fetched.filter((x) => x != null) as any[];

      let output: any = tabd;
      // Notify downstream with proper dataType structure

      if (tabd.length === 1) {
        // Single input: pass through the object directly (preserves dataType)
        output = tabd[0];
      } else if (tabd.length > 1) {
        // Multiple inputs: wrap as outputs
        output = { data: tabd, dataType: "outputs" };
      }
      data.outputCallback(data.nodeId, output)

      setTabData(tabd);
      // Local output (string)

      return { code: "success", content: JSON.stringify(tabd, null, 2) };

    } catch (error) {
      setTabData([]);
      console.error("Error processing data asynchronously:", error);
      return { code: "error", content: error instanceof Error ? error.message : String(error) };
    }
  };

  return {
    createTableData,
    parseInputData,
    parseOutputData,
    customWidgetsCallback,
    processDataAsync,
    setActiveTab,
    activeTab,
    tabData,
  };
};

export default useTableData;

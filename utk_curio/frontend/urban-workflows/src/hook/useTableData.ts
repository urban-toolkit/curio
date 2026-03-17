import { IPropagation, useFlowContext } from "../providers/FlowProvider";
import { BoxType, ResolutionType, VisInteractionType } from "../constants";
import { ICodeDataContent, ICodeData, INodeData, INode } from "../types";
import { useEffect, useRef, useState } from "react";
import { formatDate, mapTypes } from "../utils/formatters";
import { useProvenanceContext } from "../providers/ProvenanceProvider";
import { fetchData } from "../services/api";

const useTableData = ({ data }: { data: INodeData }) => {
  const [tabData, setTabData] = useState<any[]>([]);
  const [activeTab, setActiveTab] = useState<string>("0");

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

    // @ts-ignore
    if (parsedOutput != "") {
        // let parsedOutput = parsedOutput;
        // parsedOutput.data = parsedOutput.data;
        // console.log("Creating table", parsedOutput);
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
        }
        else if(parsedOutput.dataType == "geodataframe" && parsedOutput.data.features.length > 0) {
            let columns = Object.keys(parsedOutput.data.features[0].properties);

            for (let i = 0; i < parsedOutput.data.features.length; i++) {
                let element: any = {};

                for (const column of columns) {
                    element[column] =
                        parsedOutput.data.features[i].properties[column];
                }

                tableData.push(element);
            }
        }
    }

    return tableData;
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
      let tabd = fetched.filter((x) => x != null) as any[];

      tabd = tabd.map ((item) => {
        console.log(item);
        let parsedInput = Object.assign({}, item);
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

        // if (item.dataType === "geodataframe" && item.data?.features) {
        //   for (const feature of item.data.features) {
        //     if (feature.properties && feature.properties.interacted === undefined) {
        //       feature.properties.interacted = "0";
        //     }
        //   }
        // } else if (item.dataType === "dataframe" && item.data) {
        //   const columns = Object.keys(item.data);
        //   if (columns.length > 0 && item.data.interacted === undefined) {
        //     const dfIndices = Object.keys(item.data[columns[0]]);
        //     item.data.interacted = {};
        //     for (const idx of dfIndices) {
        //       item.data.interacted[idx] = "0";
        //     }
        //   }
        // }
      });

      // Build the downstream output exactly as the original DataPoolBox did:
      // send the fetched data object directly (no path attached) so downstream
      // boxes like UTK use the in-memory data rather than re-fetching from the
      // server and losing the initialised 'interacted' field.
      let callbackOutput: any;
      let contentOutput: any;

      if (tabd.length === 1) {
        callbackOutput = tabd[0];           // plain fetched object, no path
        contentOutput  = tabd[0];           // object stored in output.content
      } else if (tabd.length > 1) {
        callbackOutput = { data: tabd, dataType: "outputs" };
        contentOutput  = { data: tabd, dataType: "outputs" };
      } else {
        callbackOutput = null;
        contentOutput  = '';
      }

      if (callbackOutput !== null) {
        data.outputCallback(data.nodeId, callbackOutput);
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
    customWidgetsCallback,
    processDataAsync,
    setActiveTab,
    activeTab,
    tabData,
  };
};

export default useTableData;

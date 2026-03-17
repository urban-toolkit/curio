import React, { useState, useEffect, useMemo } from 'react';
import { BoxLifecycleHook } from '../../registry/types';
import useTableData from '../../hook/useTableData';
import { ICodeData, ICodeDataContent } from '../../types';
import { IPropagation } from '../../providers/FlowProvider';
import DataPoolContent from './components/DataPoolContent';
import { ResolutionType, VisInteractionType, BoxType } from '../../constants';

export const useDataPoolLifecycle: BoxLifecycleHook = (data, boxState) => {
  const [output, setOutput] = useState<ICodeData>({ code: '', content: '' });
  const [plotResolutionMode, setPlotResolutionMode] = useState<string>(ResolutionType.OVERWRITE);// how interaction conflicts are solved in the context of one plot
  const [resolutionMode, setResolutionMode] = useState<string>(ResolutionType.OVERWRITE);// how interaction conflicts between plots are resolved

  const {
    createTableData,
    customWidgetsCallback,
    processDataAsync,
    activeTab,
    setActiveTab,
    tabData,
  } = useTableData({ data });

  useEffect(() => {
    let cancelled = false;
    const loadData = async () => {
      const result = await processDataAsync();
      if (!cancelled) setOutput(result as ICodeData);
    };
    loadData();
    return () => { cancelled = true; };
  }, [data.input, data.newPropagation]);

  useEffect(() => {
    if (output.content != "" && data.interactions != undefined) {

      // output.content is always the fetched data object (matching original DataPoolBox).
      // For multi-input it is the {dataType:"outputs", data:[...]} wrapper; interactions
      // currently operate on the first item in that case.
      let parsedInput: ICodeDataContent;
      if (typeof output.content === 'object' && (output.content as any).dataType === 'outputs') {
        parsedInput = (output.content as any).data[0];
      } else {
        parsedInput = output.content as ICodeDataContent;
      }

      let interactedIndices: any = []; // between visualizations

      let columns: string[] = [];
      let dfIndices: string[] = [];

      if (parsedInput.dataType == "dataframe") {
          columns = Object.keys(parsedInput.data);
          dfIndices = Object.keys(parsedInput.data[columns[0]]);
      }
      // console.log(data.interactions);
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
                      indices: details[select].data.map(
                          (index: number) => {
                              return index;
                          }
                      ),
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

                  if (parsedInput.dataType == "dataframe")
                      objectsCounter = dfIndices.length;
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
                                  if (!brushBoundaries.includes(parsedInput.data.features[i].properties[brushedColumn])) {
                                      interacted = false;
                                      break;
                                  }
                              }
                          } else if (brushBoundaries.length == 2) {
                              // numerical interval

                              let value = -1;

                              if (parsedInput.dataType == "dataframe") {
                                  value = parsedInput.data[brushedColumn][dfIndices[i]];
                              } else if (
                                  parsedInput.dataType == "geodataframe"
                              ) {
                                  value = parsedInput.data.features[i].properties[brushedColumn];
                              }

                              if (
                                  value < brushBoundaries[0] ||
                                  value > brushBoundaries[1]
                              ) {
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
              } else if (
                  details[select].type == VisInteractionType.UNDETERMINED
              ) {
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
                  interactedList = allArrays.reduce(
                      (a: number[], b: number[]) =>
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
              interactedList = allArrays.reduce(
                  (a: number[], b: number[]) =>
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

      if (parsedInput.dataType == "dataframe")
          objectsCounter = dfIndices.length;
      else if (parsedInput.dataType == "geodataframe")
          objectsCounter = parsedInput.data.features.length;

      if (!buildingsLayer) {
          for (let i = 0; i < objectsCounter; i++) {
              // console.log(interactedList);
              if (interactedList.includes(i)) {
                  if (parsedInput.dataType == "dataframe") {
                      parsedInput.data.interacted[dfIndices[i]] = "1"; // 1 -> interacted with

                      if (parsedInput.data.linked != undefined) {
                          for (const index of parsedInput.data.linked[
                              dfIndices[i]
                          ]) {
                              propagationObj.propagation[index] = "1";
                          }
                      }
                  } else if (parsedInput.dataType == "geodataframe") {
                      parsedInput.data.features[i].properties.interacted = "1"; // 1 -> interacted with
                      if (parsedInput.data.features[i].properties.linked != undefined) {
                          for (const index of parsedInput.data.features[i].properties[dfIndices[i]].linked) {
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
                      parsedInput.data.features[i].properties.interacted = "0";
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

      const clonedOutput = JSON.parse(JSON.stringify(newOutput));
      setOutput({ code: "success", content: clonedOutput });
      data.outputCallback(data.nodeId, clonedOutput);

      // call callback propagation
      data.propagationCallback(propagationObj);
    }
  }, [data.interactions]);

  useEffect(() => {
    const selectBetween = document.getElementById(
        data.nodeId + "_" + "select_between"
    );
    if (!selectBetween) return;

    selectBetween.addEventListener("change", (event) => {
        if (event.target != null) {
            let target = event.target as HTMLOptionElement;
            const selectedOption = target.value;
            setResolutionMode(selectedOption);
        }
    });

    const selectIntra = document.getElementById(
        data.nodeId + "_" + "select_intra"
    );
    if (!selectIntra) return;

    selectIntra.addEventListener("change", (event) => {
        if (event.target != null) {
            let target = event.target as HTMLOptionElement;
            const selectedOption = target.value;
            setPlotResolutionMode(selectedOption);
        }
    });
  }, []);

  const tableData = useMemo(() => {
    // output.content is always a data object (never a JSON string) so we can
    // use it directly — mirroring the original DataPoolBox useEffect([output]).
    // For multi-input the content is {dataType:"outputs", data:[...]}: pick the
    // active tab's item; for single input use it as-is.
    if (output.content && output.content !== '') {
      const content = output.content as any;
      const source: ICodeDataContent =
        content.dataType === 'outputs'
          ? content.data[parseInt(activeTab)]
          : content;
      if (source) return createTableData(source);
    }
    // Fallback to tabData before output is first populated
    const displayTable = tabData[parseInt(activeTab)];
    if (displayTable) return createTableData(displayTable as ICodeDataContent);
    return [];
  }, [output, tabData, activeTab, createTableData]);

  const contentComponent = (
    <DataPoolContent
      activeTab={activeTab}
      onSelectTab={setActiveTab}
      tabData={tabData}
      tableData={tableData}
      data={data}
    />
  );

  return {
    contentComponent,
    customWidgetsCallback,
    setOutputCallbackOverride: setOutput,
    outputOverride: output,
    setSendCodeCallbackOverride: () => {},
  };
}

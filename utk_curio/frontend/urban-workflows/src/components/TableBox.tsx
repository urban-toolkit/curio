import React, { useState, useEffect, useRef } from "react";
import { Handle, Position } from "reactflow";
import BoxEditor from "./editing/BoxEditor";

import { Template, useTemplateContext } from "../providers/TemplateProvider";
import { BoxContainer, buttonStyle } from "./styles";
import CSS from "csstype";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faGear, faCircleInfo } from "@fortawesome/free-solid-svg-icons";

import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Paper from "@mui/material/Paper";
import "./Box.css"

// Bootstrap
import "bootstrap/dist/css/bootstrap.min.css";
import { BoxType } from "../constants";
import DescriptionModal from "./DescriptionModal";
import TemplateModal from "./TemplateModal";
import { useUserContext } from "../providers/UserProvider";
import { useProvenanceContext } from "../providers/ProvenanceProvider";
import { useFlowContext } from "../providers/FlowProvider";
import { OutputIcon } from "./edges/OutputIcon";
import { InputIcon } from "./edges/InputIcon";

function TableBox({ data, isConnectable }) {
  const [output, setOutput] = useState<{ code: string; content: string }>({
    code: "",
    content: "",
  }); // stores the output produced by the last execution of this box
  const [code, setCode] = useState<string>("");
  const [templateData, setTemplateData] = useState<Template | any>({});
  const [outputTable, setOutputTable] = useState<any[]>([]); // stores the output in a format used by the table

  const [showTemplateModal, setShowTemplateModal] = useState(false);
  const [showDescriptionModal, setDescriptionModal] = useState(false);

  const dataInputBypass = useRef(false);

  const { boxExecProv } = useProvenanceContext();
  const { workflowNameRef } = useFlowContext();
  const { user } = useUserContext();

  useEffect(() => {
    if (data.templateId != undefined) {
      setTemplateData({
        id: data.templateId,
        type: BoxType.VIS_TABLE,
        name: data.templateName,
        description: data.description,
        accessLevel: data.accessLevel,
        code: data.defaultCode,
        custom: data.customTemplate,
      });
    }
  }, [data.templateId]);

  const setTemplateConfig = (template: Template) => {
    setTemplateData({ ...template });
  };

  const closeModal = () => {
    setShowTemplateModal(false);
  };

  const promptDescription = () => {
    setDescriptionModal(true);
  };

  const closeDescription = () => {
    setDescriptionModal(false);
  };

  useEffect(() => {
    if (dataInputBypass.current) {
      const formatDate = (date: Date) => {
        // Get individual date components
        const month = date.toLocaleString("default", { month: "short" });
        const day = date.getDate();
        const year = date.getFullYear();
        const hours = date.getHours();
        const minutes = date.getMinutes();
        const seconds = date.getSeconds();

        // Format the string
        const formattedDate = `${month} ${day} ${year} ${hours}:${minutes}:${seconds}`;

        return formattedDate;
      };

      let startTime = formatDate(new Date());

      const getType = (inputs: any[]) => {
        let typesInput: string[] = [];

        for (const input of inputs) {
          let parsedInput = input;

          if (typeof input == "string") parsedInput = JSON.parse(parsedInput);

          if (parsedInput.dataType == "outputs") {
            typesInput = typesInput.concat(getType(parsedInput.data));
          } else {
            typesInput.push(parsedInput.dataType);
          }
        }

        return typesInput;
      };

      const mapTypes = (typesList: string[]) => {
        let mapTypes: any = {
          DATAFRAME: 0,
          GEODATAFRAME: 0,
          VALUE: 0,
          LIST: 0,
          JSON: 0,
        };

        for (const typeValue of typesList) {
          if (
            typeValue == "int" ||
            typeValue == "str" ||
            typeValue == "float" ||
            typeValue == "bool"
          ) {
            mapTypes["VALUE"] = 1;
          } else if (typeValue == "list") {
            mapTypes["LIST"] = 1;
          } else if (typeValue == "dict") {
            mapTypes["JSON"] = 1;
          } else if (typeValue == "dataframe") {
            mapTypes["DATAFRAME"] = 1;
          } else if (typeValue == "geodataframe") {
            mapTypes["GEODATAFRAME"] = 1;
          }
        }

        return mapTypes;
      };

      let typesInput: string[] = [];

      if (data.input != "") {
        typesInput = getType([data.input]);
        setOutput({ code: "success", content: data.input });
        data.outputCallback(data.nodeId, data.input);
      }

      let typesOuput: string[] = [...typesInput];

      boxExecProv(
        startTime,
        startTime,
        workflowNameRef.current,
        BoxType.VIS_TABLE + "-" + data.nodeId,
        mapTypes(typesInput),
        mapTypes(typesOuput),
        ""
      );
    }

    dataInputBypass.current = true;
  }, [data.input]);

  const createTable = (output: string) => {
    let tableData = [];

    if (output != "") {
      let parsedOutput = JSON.parse(output);
      parsedOutput.data = JSON.parse(parsedOutput.data);

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
    }

    return tableData;
  };

  const shortenString = (str: string) => {
    if (str.length > 15) {
      return str.slice(0, 15) + "...";
    } else {
      return str;
    }
  };

  const ContentComponent = ({
    outputTable,
    data,
  }: {
    outputTable: any;
    data: any;
  }) => {
    return (
      <div className="nowheel" style={{ overflowY: "auto", height: "100%" }}>
        <TableContainer component={Paper}>
          <Table aria-label="simple table">
            {outputTable.length > 0 ? (
              <TableHead>
                <TableRow>
                  {Object.keys(outputTable[0]).map((column, index) => {
                    return (
                      <TableCell
                        style={{ fontWeight: "bold" }}
                        key={"cell_header_" + index + "_" + data.nodeId}
                        align="right"
                      >
                        {column}
                      </TableCell>
                    );
                  })}
                </TableRow>
              </TableHead>
            ) : null}

            <TableBody>
              {outputTable.slice(0, 100).map((row: any, index: any) => {
                return (
                  <TableRow
                    key={"row_" + index + data.nodeId}
                    sx={{ "&:last-child td, &:last-child th": { border: 0 } }}
                  >
                    {Object.keys(row).map((column, columnIndex) => {
                      return (
                        <TableCell
                          key={
                            "cell_" +
                            columnIndex +
                            "_" +
                            index +
                            "_" +
                            data.nodeId
                          }
                          align="right"
                        >
                          {shortenString(row[column].toString())}
                        </TableCell>
                      );
                    })}
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </TableContainer>
      </div>
    );
  };

  useEffect(() => {
    setOutputTable(createTable(output.content));
  }, [output]);

  return (
    <>
      <Handle
        type="target"
        position={Position.Left}
        id="in"
        isConnectable={isConnectable && (data.suggestionType == undefined || data.suggestionType == "none")}
      />
      <Handle
        type="source"
        position={Position.Right}
        id="out"
        isConnectable={isConnectable && (data.suggestionType == undefined || data.suggestionType == "none")}
      />
      {/* Data flows in both ways */}
      <Handle
        type="source"
        position={Position.Top}
        id="in/out"
        isConnectable={isConnectable && (data.suggestionType == undefined || data.suggestionType == "none")}
      />
      <BoxContainer
        nodeId={data.nodeId}
        data={data}
        templateData={templateData}
        setOutputCallback={setOutput}
        promptDescription={promptDescription}
      >
        <InputIcon type="1" />
        <DescriptionModal
          nodeId={data.nodeId}
          boxType={BoxType.VIS_TABLE}
          name={templateData.name}
          description={templateData.description}
          accessLevel={templateData.accessLevel}
          show={showDescriptionModal}
          handleClose={closeDescription}
          custom={templateData.custom}
        />
        <TemplateModal
          templateId={templateData.id}
          callBack={setTemplateConfig}
          show={showTemplateModal}
          handleClose={closeModal}
          boxType={BoxType.DATA_LOADING}
          code={code}
        />
        <BoxEditor
          setSendCodeCallback={(_: any) => {}}
          contentComponent={
            <ContentComponent outputTable={outputTable} data={data} />
          }
          code={false}
          grammar={false}
          widgets={false}
          provenance={false}
          setOutputCallback={setOutput}
          data={data}
          output={output}
          boxType={BoxType.VIS_TABLE}
          defaultValue={""}
          readOnly={false}
        />

        <OutputIcon type="1" />
      </BoxContainer>
    </>
  );
}

export default TableBox;

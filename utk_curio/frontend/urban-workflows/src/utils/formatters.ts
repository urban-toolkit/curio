export const formatDate = (date: Date) => {
    const month = date.toLocaleString("default", { month: "short" });
    const day = date.getDate();
    const year = date.getFullYear();
    const hours = date.getHours();
    const minutes = date.getMinutes();
    const seconds = date.getSeconds();

    return `${month} ${day} ${year} ${hours}:${minutes}:${seconds}`;
};

export const getType = (inputs: any[]): string[] => {
    let typesInput: string[] = [];

    for (const input of inputs) {
      let parsedInput = input;

      if (typeof input === "string") {
        parsedInput = JSON.parse(parsedInput);
      }

      if (parsedInput.dataType === "outputs") {
        typesInput = typesInput.concat(getType(parsedInput.data));
      } else {
        typesInput.push(parsedInput.dataType);
      }
    }

    return typesInput;
};

export const mapTypes = (typesList: string[]) => {
    let mapTypes: any = {
        "DATAFRAME": 0,
        "GEODATAFRAME": 0,
        "VALUE": 0,
        "LIST": 0,
        "JSON": 0,
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
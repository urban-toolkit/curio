export const shortenString = (str: string) => {
  if (str.length > 15) {
    return str.slice(0, 15) + "...";
  } else {
    return str;
  }
};

// list will contain all coordinates from all layers
export const get_camera = (coordinates: number[]) => {
  let minLat = undefined;
  let minLon = undefined;
  let maxLat = undefined;
  let maxLon = undefined;

  for (let i = 0; i < Math.trunc(coordinates.length / 3); i++) {
    if (minLat == undefined || coordinates[i * 3] < minLat) {
      minLat = coordinates[i * 3];
    }

    if (minLon == undefined || coordinates[i * 3 + 1] < minLon) {
      minLon = coordinates[i * 3 + 1];
    }

    if (maxLat == undefined || coordinates[i * 3] > maxLat) {
      maxLat = coordinates[i * 3];
    }

    if (maxLon == undefined || coordinates[i * 3 + 1] > maxLon) {
      maxLon = coordinates[i * 3 + 1];
    }
  }

  let center = [0, 0, 1];

  if (minLat != undefined && maxLat != undefined && minLon != undefined && maxLon != undefined)
    center = [(minLat + maxLat) / 2.0, (minLon + maxLon) / 2.0, 1];

  return {
    position: center,
    direction: {
      right: [0, 0, 3000],
      lookAt: [0, 0, 0],
      up: [0, 1, 0],
    },
  };
};

export const parseDataframe = (data: any) => {
  console.log("Parsing", data);
  let columns = Object.keys(data);
  const values = Object.keys(data[columns[0]]).map((key) => {
    let obj: any = {};

    for (const column of columns) {
      obj[column] = data[column][key];
    }

    return obj;
  });

  return values;
};

export const parseGeoDataframe = (data: any) => {
  console.log("Parsing", data);
  let values = data.features.map((feature: any) => {
    return { ...feature.properties };
  });

  return values;
};
import { faCircle } from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import React from "react";

export function OutputIcon({ type }: { type: "1" | "2" | "N" }) {
  const defaultIconStyle = {
    fontSize: "0.25em",
    margin: "1px",
  };

  return (
    <div
      style={{
        position: "absolute",
        top: 0,
        bottom: 0,
        right: 0,
        display: "flex",
        alignItems: "center",
        zIndex: 50
      }}
    >
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          border: "1px solid black",
          width: "15px",
          height: "22px",
          justifyContent: "center",
          alignItems: "center",
          borderTopLeftRadius: "5px",
          borderBottomLeftRadius: "5px",
          backgroundColor: "white"
        }}
      >
        {type === "N" && (
          <>
            <FontAwesomeIcon icon={faCircle} style={defaultIconStyle} />
            <FontAwesomeIcon
              icon={faCircle}
              style={{ ...defaultIconStyle, marginLeft: "4px" }}
            />
            <FontAwesomeIcon icon={faCircle} style={defaultIconStyle} />
          </>
        )}

        {type === "2" && (
          <>
            <FontAwesomeIcon icon={faCircle} style={defaultIconStyle} />
            <FontAwesomeIcon icon={faCircle} style={defaultIconStyle} />
          </>
        )}

        {type === "1" && (
          <>
            <FontAwesomeIcon icon={faCircle} style={defaultIconStyle} />
          </>
        )}
      </div>
    </div>
  );
}

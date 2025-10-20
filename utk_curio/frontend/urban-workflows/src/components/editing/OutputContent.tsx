import React, { useEffect, useState } from "react";
import Tabs from "react-bootstrap/Tabs";
import Tab from "react-bootstrap/Tab";

// OutputContent for three tabs (Output, Error, Warning)
function OutputContent({ output }: { output: any; }) {
    
    // Tab state for three tabs
    const [tabData, setTabData] = useState<any[]>([]);

    // Build tab data from output or error
    useEffect(() => {
        // If error, show error tab with friendly and traceback
        if (output?.code === "error") {
        const match = output.content.match(/(\w+Error):/);
        // let errorType = match ? match[1] : null;
        // let friendlyMessage = errorType ? (COMMON_ERRORS[errorType] || "❗ An unknown error occurred.") : null;
        setTabData([
            {
            title: "Output",
            content: "",
            type: "output"
            },
            {
            title: "Error",
            content: {
                friendly: output.content,
                traceback: output.content
            },
            type: "error"
            },
            {
            title: "Warning",
            content: { friendly: null, traceback: null },
            type: "warning"
            }
        ]);
        } else {
        setTabData([
            {
            title: "Output",
            content: output.content,
            type: "output"
            },
            {
            title: "Error",
            content: { friendly: null, traceback: null },
            type: "error"
            },
            {
            title: "Warning",
            content: { friendly: null, traceback: null },
            type: "warning"
            }
        ]);
        }
    }, [output]);

    return (
      <Tabs
        id="computation-tabs"
        className="mb-2"
      >
        <Tab eventKey="0" title="Output">
          <div style={{ padding: "15px" }}>
            <h6>Output</h6>
            <div style={{ fontSize: "12px", color: "#666" }}>{tabData[0]?.content || "No output available."}</div>
          </div>
        </Tab>
        <Tab eventKey="1" title="Error">
          <div style={{
            padding: "15px",
            display: "flex",
            flexDirection: "column",
            height: "100%",
            minHeight: 300,
            maxHeight: 600,
          }}>
            <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
              {(tabData[1]?.content?.friendly || tabData[1]?.content?.traceback) ? (
                <div className="error-traceback-scroll" style={{ flex: 1, display: "flex", flexDirection: "column", padding: 0 }}>
                  {/* Error message */}
                  {/* {tabData[1]?.content?.friendly && (
                    <div
                      style={{
                        background: "#fff8e1",
                        color: "#6d4c41",
                        padding: "16px",
                        fontWeight: 600,
                        fontSize: "1.1em",
                        borderTopLeftRadius: "8px",
                        borderTopRightRadius: "8px",
                        borderBottom: tabData[1]?.content?.traceback ? "1px solid #eee" : undefined
                      }}
                    >
                      {tabData[1].content.friendly}
                    </div>
                  )} */}
                  {/* Traceback */}
                  {tabData[1]?.content?.traceback && (
                    <div
                      style={{
                        background: "#ffebee",
                        color: "#b71c1c",
                        padding: "12px",
                        fontWeight: 400,
                        fontFamily: "monospace",
                        borderBottomLeftRadius: "8px",
                        borderBottomRightRadius: "8px",
                        display: "flex",
                        flexDirection: "column"
                      }}
                    >
                      <div style={{ fontWeight: 600 }}>Traceback:</div>
                      <pre style={{ margin: 0, fontSize: "1em", background: "none", color: "inherit" }}>{tabData[1].content.traceback}</pre>
                    </div>
                  )}
                </div>
              ) : (
                <div>No errors available</div>
              )}
            </div>
          </div>
        </Tab>
        <Tab eventKey="2" title="Warning">
          <div style={{ padding: "15px" }}>
            {tabData[2]?.content?.friendly && (
              <div style={{ background: "#fffbe6", color: "#8a6d3b", padding: "10px", borderRadius: "5px", fontWeight: "bold" }}>
                {tabData[2].content.friendly}
              </div>
            )}
            {tabData[2]?.content?.traceback && (
              <div style={{ background: "#e2e3e5", color: "#383d41", padding: "10px", borderRadius: "5px" }}>
                <span role="img" aria-label="Traceback">📄 Traceback:</span><br />
                <pre style={{ margin: 0, fontSize: "1em", fontFamily: "monospace" }}>{tabData[2].content.traceback}</pre>
              </div>
            )}
            {!tabData[2]?.content?.friendly && !tabData[2]?.content?.traceback && (
              <div>No warnings available</div>
            )}
          </div>
        </Tab>
      </Tabs>
    );
};

export default OutputContent;
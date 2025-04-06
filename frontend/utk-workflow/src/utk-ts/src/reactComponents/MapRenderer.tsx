import React from "react";
import './MapRenderer.css';
import { SideBarMapWidgets } from "./SideBarMapWigets";
import { WidgetType } from "../constants";
import { IGenericWidget } from "../interfaces";

// declaring the types of the props
type MapRendererProps = {
  obj: any,
  viewId: string,
  mapWidgets: {type: WidgetType, obj: any, grammarDefinition: IGenericWidget | undefined}[] // each viewObj has a an object representing its logic
  x: number,
  y: number,
  width: number,
  height: number,
  listLayers: any,
  knotVisibility: any,
  genericPlots: any,
  togglePlots: any,
  inputBarId: string,
  componentId: string,
  editGrammar: any,
  broadcastMessage: any
}

export const MapRendererContainer = ({obj, viewId, mapWidgets, x, y, width, height, listLayers, knotVisibility, genericPlots, togglePlots, inputBarId, componentId, editGrammar, broadcastMessage}:MapRendererProps) =>{

    return(
      <React.Fragment>
        <div style={{padding: 0, width: "100%", height: "100%"}}>
          <div id={viewId} className="mapView" style={{width: "100%", height: "100%"}}>
          </div>
          <div id='svg_div'>
            <svg id='svg_element' xmlns="http://www.w3.org/2000/svg" style={{"display": "none"}}>
            </svg>
          </div>
        </div>

        <SideBarMapWidgets 
          mapWidgets={mapWidgets}
          x={x}
          y={y}
          mapWidth={width}
          mapHeight={height}
          listLayers={listLayers}
          knotVisibility={knotVisibility}
          inputBarId={inputBarId}
          genericPlots={genericPlots}
          togglePlots={togglePlots}
          componentId={componentId}
          editGrammar={editGrammar}
          broadcastMessage={broadcastMessage}
        />

        {/* <div style={{position: "absolute", height: "160px", bottom: 0, width: (divWidth/12)*window.innerWidth, backgroundColor: "rgba(200,200,200,0.3)", padding: 0}}>
          
          <Row md={12} style={{padding: 0, margin: 0}}>

            <Col md={4} style={{padding: 0, margin: 0, height: "160px"}}>
                {
                  systemMessages.map((item, index) => (
                      <p style={{color: item.color, width: ((divWidth/12)*window.innerWidth)/3, textAlign: "center", fontWeight: "bold", marginTop: "18px", marginBottom: "5px", position: "absolute"}} key={index}>{item.text}</p>
                  ))
                } 

            </Col>

            <Col md={4} style={{padding: 0, margin: 0, height: "160px"}}>
              <div className="d-flex align-items-center justify-content-center" style={{height: "160px"}}>
                <VisWidget 
                    genericScreenPlotToggle = {genericScreenPlotToggle}
                    listPlots = {listPlots}
                    modifyLabelPlot = {modifyLabelPlot}
                  />
              </div>
            </Col>

          </Row>

        </div> */}
      </React.Fragment>
    )
}

// knotToggle = {(id: string) => app.map.toggleKnot(id)}                      
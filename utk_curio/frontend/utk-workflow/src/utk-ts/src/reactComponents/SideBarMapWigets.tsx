import React, { useState, useEffect } from "react";
import { GrammarType, WidgetType } from "../constants";
import { IGenericWidget } from "../interfaces";
import { ToggleKnotsWidget } from './ToggleKnotsWidget';
import { SearchWidget } from './SearchWidget';
import {Row} from 'react-bootstrap';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faLayerGroup, faChartSimple, faEyeSlash, faSearch, faEye, faCode } from '@fortawesome/free-solid-svg-icons'
import * as d3 from "d3";
import { InteractionChannel } from "../interaction-channel";
import { ColorScaleContainer } from './ColorScale';
import { Environment } from "../environment";

type SideBarMapWidgetsProps = {
    x: number,
    y: number,
    mapWidth: number,
    mapHeight: number,
    listLayers: any,
    knotVisibility: any,
    inputBarId: string,
    genericPlots: any,
    togglePlots: any,
    mapWidgets: {type: WidgetType, obj: any, grammarDefinition: IGenericWidget | undefined}[] // each viewObj has a an object representing its logic
    componentId: string,
    editGrammar: any,
    broadcastMessage: any
}

export var GrammarPanelVisibility = true;
export const SideBarMapWidgets = ({x, y, mapWidth, mapHeight, listLayers, knotVisibility, inputBarId, genericPlots, togglePlots, mapWidgets, componentId, editGrammar, broadcastMessage}:SideBarMapWidgetsProps) =>{

    const handleClickLayers = (e: any) => {

      if(d3.select("#toggle_knot_widget").style("display") == "block"){
          d3.select("#toggle_knot_widget").style("display", "none");
      }else{
        d3.select("#toggle_knot_widget").style("display", "block");
      }
    }

    const handleClickSearch = (e: any) => {

      if(d3.select("#search_widget").style("display") == "block"){
          d3.select("#search_widget").style("display", "none");
      }else{
        d3.select("#search_widget").style("display", "block");
      }
    }

    const handleClickHideGrammar = (e: any) => {
      GrammarPanelVisibility = !(GrammarPanelVisibility);
      InteractionChannel.getModifyGrammarVisibility()();
    }

    // const handleTogglePlots = (e: any) => {
    //   togglePlots();
    // }

    const [colorScales, setColorScales] = useState<{range: number[], domain: number[], cmap: string, id: string, scale: string, visible: boolean}[]>([]);

    useEffect(() => {

      let colorScalesAux: any = [];

      for(const group of Object.keys(listLayers)){
          for(const layer of listLayers[group]){
            colorScalesAux.push({range: layer.range, domain: layer.domain, cmap: layer.cmap, id: layer.id, scale: layer.scale, visible: false});
          }
      }

      setColorScales(colorScalesAux);

    }, [listLayers]);

    const toggleColorScaleVisibility = (id: string) => {
      let colorScalesAux: any = [];
      
      for(const colorScale of colorScales){

        colorScalesAux.push({...colorScale});

        if(colorScale.id == id){
          colorScalesAux[colorScalesAux.length-1].visible = !colorScalesAux[colorScalesAux.length-1].visible;
        }
      }

      setColorScales(colorScalesAux);
    }

    return (
        <React.Fragment>
          {
              colorScales.map((colorScaleInfo: {range: number[], domain: number[], cmap: string, id: string, scale: string, visible: boolean}, index: number) => (
                  <ColorScaleContainer 
                      id={colorScaleInfo.id}
                      x={20}
                      y={-250}
                      range={colorScaleInfo.range}
                      domain={colorScaleInfo.domain}
                      cmap={colorScaleInfo.cmap}
                      scale={colorScaleInfo.scale}
                      disp={colorScaleInfo.visible}
                      keyValue={index}
                      key={"colorScaleContainer_"+index}
                  />
              ))
          }
          {mapWidgets.length >= 1 ? <div style={{backgroundColor: "white", width: "75px", position: "absolute", right: "10px", top: "10px", padding: "5px", borderRadius: "8px", border: "1px solid #dadce0", opacity: 0.9, boxShadow: "0 2px 8px 0 rgba(99,99,99,.2)"}}>
            <Row>
              {
                mapWidgets.map((component, index) => {
                  if(component.type == WidgetType.TOGGLE_KNOT){
                    return <FontAwesomeIcon key={"widget_"+index} size="2x" style={{color: "#696969", padding: 0, marginTop: "5px", marginBottom: "5px"}} icon={faLayerGroup} onClick={handleClickLayers} />
                  }else if(component.type == WidgetType.SEARCH){
                    return <FontAwesomeIcon key={"widget_"+index} size="2x" style={{color: "#696969", padding: 0, marginTop: "5px", marginBottom: "5px"}} icon={faSearch} onClick={handleClickSearch} />
                  }else if(component.type == WidgetType.HIDE_GRAMMAR){
                    if(GrammarPanelVisibility){
                      return <FontAwesomeIcon key={"widget_"+index} size="2x" style={{color: "#696969", padding: 0, marginTop: "5px", marginBottom: "5px"}} icon={faEye} onClick={handleClickHideGrammar} />
                    }
                    else{
                      return <FontAwesomeIcon key={"widget_"+index} size="2x" style={{color: "#696969", padding: 0, marginTop: "5px", marginBottom: "5px"}} icon={faEyeSlash} onClick={handleClickHideGrammar} />
                    }
                  }
                })
              }
              {/* {genericPlots.filter((plot: any) => {return plot.floating;}).length > 0 ? <FontAwesomeIcon size="2x" style={{color: "#696969", padding: 0, marginTop: "5px", marginBottom: "5px"}} icon={faChartSimple} onClick={handleTogglePlots} /> : null} */}
            </Row>
          </div> : null}
          {!Environment.serverless ? <div style={{ backgroundColor: "white", width: "75px", position: "absolute", right: "10px", bottom: "10px", padding: "5px", borderRadius: "8px", border: "1px solid #dadce0", opacity: 0.9, boxShadow: "0 2px 8px 0 rgba(99,99,99,.2)" }}>
              <Row>
                  <FontAwesomeIcon size="2x" style={{ color: "#696969", padding: 0, marginTop: "5px", marginBottom: "5px" }} icon={faCode} onClick={() => editGrammar(componentId, GrammarType.MAP)} />
                  {/* {genericPlots.filter((plot: any) => {return plot.floating;}).length > 0 ? <FontAwesomeIcon size="2x" style={{color: "#696969", padding: 0, marginTop: "5px", marginBottom: "5px"}} icon={faChartSimple} onClick={handleTogglePlots} /> : null} */}
              </Row>
          </div> : null}

            {
              mapWidgets.map((component, index) => {
                if(component.type == WidgetType.TOGGLE_KNOT){
                  return <React.Fragment key={"toggle_knot_"+index}>
                    <div className='component' id="toggle_knot_widget" style={{position: "absolute", right: 100, top: 10, width: "50%", borderRadius: "8px", border: "1px solid #dadce0", opacity: 0.9, boxShadow: "0 2px 8px 0 rgba(99,99,99,.2)", display: "none"}}>
                      <ToggleKnotsWidget
                        obj = {component.obj}
                        listLayers = {listLayers}
                        knotVisibility = {knotVisibility}
                        viewId = {"toggle_knot_"+index}
                        grammarDefinition = {component.grammarDefinition}
                        broadcastMessage = {broadcastMessage}
                        toggleColorScaleVisibility = {toggleColorScaleVisibility}
                      />
                    </div>
                  </React.Fragment>
                }else if(component.type == WidgetType.SEARCH){
                  return <React.Fragment key={"search_"+index}>
                    <div id="search_widget" style={{borderRadius: "8px", position: "absolute", left: mapWidth - 240, top: 10, opacity: 0.9, display: "none"}}>
                      <SearchWidget 
                        obj = {component.obj}
                        viewId = {"search_"+index}
                        inputId = {inputBarId}
                      />
                    </div>
                  </React.Fragment>
                }
              })
            }
      </React.Fragment>
    );
}
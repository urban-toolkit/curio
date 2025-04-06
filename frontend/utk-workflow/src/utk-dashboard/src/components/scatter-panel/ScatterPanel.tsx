import { VegaLite } from 'react-vega'
import { VisualizationSpec } from 'vega-embed'
import { FieldType } from "../../types/Types"
import { useEffect, useState } from 'react'
import "./ScatterPanel.css"
import Intermediary from '../../intermediary/Intermediary'

// import $ from "jquery"

interface ScatterPanelProps {
    fields: FieldType[]
    data: any[]
    setScatter: any
}

interface DropdownProps {
  axis: "X" | "Y"
  label: string
  activeField: FieldType | Record<string, never>
}

const ScatterPanel = ({ fields, data, setScatter } : ScatterPanelProps) => {
   
  const [xDrop, setXDrop] = useState<DropdownProps>({ axis: "X", label: "", activeField: {}})
  const [yDrop, setYDrop] = useState<DropdownProps>({ axis: "Y", label: "", activeField: {}})
  
  
  useEffect(() => {
    const updateDropdowns = () => {
      const xD = {...xDrop}
      const yD = {...yDrop}
      
      if(fields.length === 0) {
        xD.label = ""
        xD.activeField = {}

        yD.label = ""
        yD.activeField = {}
        
      } else {
        xD.label = fields[0].nick
        xD.activeField = fields[0]

        yD.label = fields[1].nick
        yD.activeField = fields[1]
      }

      setXDrop(xD)
      setYDrop(yD)
    } 
    
    updateDropdowns()
    
  },[fields])
  
  if(fields.length === 0 || data.length === 0) { 
    return <div></div> 
  }

  async function handleClick(ax: DropdownProps, fld:FieldType, setAxis: typeof setXDrop | typeof setYDrop) {
    // $(".scatter-dropdown-content").hide()
    
    // Update Scatter
    const fldX = ax.axis === "X" ? fld.key : xDrop.activeField.key
    const fldY = ax.axis === "Y" ? fld.key : yDrop.activeField.key
    const newScatter = await Intermediary.getScatter(fldX, fldY)
    
    setScatter(newScatter.data)
    setAxis({ axis: ax.axis, label: fld.nick, activeField: fld})
  }
  
  const scatter: VisualizationSpec = {
    "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
    // "data": {"url": "https://raw.githubusercontent.com/vega/vega/main/docs/data/cars.json"},
    "data": {"values": data},
    "width": 250,
    "height": 250,
    "mark": "circle",
    "encoding": {
      "x": {"field": `${xDrop.activeField.key}`, "type": "quantitative", "title": `${xDrop.activeField.nick}`},
      "y": {"field": `${yDrop.activeField.key}`, "type": "quantitative", "title": `${yDrop.activeField.nick}`}
    },
  }

  // return <div>To do</div>
 
  return(
    <>
    <div className="scatter-dropdown">
      <button className="scatter-dropbtn">{`${xDrop.axis}: ${xDrop.label}`}</button>
      <div className="scatter-dropdown-content">
        {
          fields.map(f => {
            return (
              <button 
                className='dropdown-item' 
                key={`scatter-drop-item-${f.key}`}
                onClick={() => handleClick(xDrop, f, setXDrop)}>{`${f.name}`}</button>
            )
          })
        }
      </div>
    </div>

    <div className="scatter-dropdown">
      <button className="scatter-dropbtn">{`${yDrop.axis}: ${yDrop.label}`}</button>
      <div className="scatter-dropdown-content">
        {
          fields.map(f => {
            return (
              <button 
                className='dropdown-item' 
                key={`scatter-drop-item-${f.key}`}
                onClick={() => handleClick(yDrop, f, setYDrop)}>{`${f.name}`}</button>
            )
          })
        }
      </div>
    </div>
      <VegaLite
        spec={scatter}
        actions={false}
        renderer={'svg'}
      />
    </>
  )
}

export { ScatterPanel }
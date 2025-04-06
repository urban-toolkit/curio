import {memo} from "react"

import { Modal } from "react-bootstrap"
import { FieldType, TimeSeriesEntry } from "../../types/Types"
import Tseries from "../tseries/Tseries"
import { useState } from "react"
import TseriesFocusCtx from "../tseries/TseriesFocusCtx"

interface TemporalPanelProps {
  fields: FieldType[]
  timeSeries: Record<string, TimeSeriesEntry[] | []>
  activeTime: number
}

const TemporalPanel = memo(({ fields, timeSeries, activeTime} : TemporalPanelProps) => {
    
  const [fcIsOpen, setFcIsOpen] = useState(false)
  const [activeFcTseries, setFcTseries] = useState<string>("")

  if (Object.keys(timeSeries).length === 0) {
    return <div></div>
  } 

  return (
    <div>
      {
        Object.keys(timeSeries).map((field, idx) => {
          const fieldObj = fields.filter(fld => fld.key === field)[0]

          const k    = field as keyof typeof timeSeries
          const nick = fieldObj.nick
          const unit = fieldObj.unit
          const name = `${fieldObj.name} (${unit})`

          return (
            <div key={`temporal-row-${idx}`} className="row mt-1 mb-1 align-items-center">

              {/* Line Charts */}
              
              <div className="col">{`${nick} (${unit})`}</div>
              <div className="col">
              <Tseries data={timeSeries[k]} time={activeTime}/>
              </div>
  
              {/* Focus + Context */}
              
              <div className="col">
                <button 
                    type="button" 
                    className="btn btn-outline-primary btn-sm"
                    onClick={() => { 
                    setFcTseries(name)
                    setFcIsOpen(true)
                }}
                >
                    <i className="fa fa-search-plus" aria-hidden="true"></i>
                </button>
                
                <Modal show={fcIsOpen} onHide={() => setFcIsOpen(false)} size="lg" animation={true}>
                    <Modal.Header closeButton>
                    <Modal.Title> {activeFcTseries} </Modal.Title>
                    </Modal.Header>
                    <Modal.Body>
                    <TseriesFocusCtx data={timeSeries[k]}/>
                    </Modal.Body>
                </Modal>
              </div>
            </div>
          )
        })
      }
    </div>
  )
})

export {TemporalPanel}
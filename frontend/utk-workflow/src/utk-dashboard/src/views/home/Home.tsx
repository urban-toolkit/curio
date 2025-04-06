import { useEffect, useState } from 'react'

import { Nav } from "../../template/nav"
import { Main } from "../../template/main"

import { Map } from "../../components/map"

import "./Home.css"

import Intermediary from '../../intermediary/Intermediary'


import { FieldType } from '../../types/Types'

import { TemporalPanel } from '../../components/temporal-panel'
import { TemporalOptions } from '../../components/temporal-options'
import { HmatPanel } from '../../components/hmat-panel'
import { ScatterPanel } from '../../components/scatter-panel'

import { TimeBtn } from '../../components/time-btn'

function Home() {

  const initialTemporalPanelData: any = {}

  // Variables
  const [fieldsList, setFieldsList]           = useState<FieldType[] | []>([])
  const [temporalPanelData, setTempPanelData] = useState(initialTemporalPanelData)
  const [scatter, setScatter]                 = useState<any[]>([])
  const [hmat, setHmat]                       = useState<any[]>([])
  const [scatterX, setScatterX]               = useState<string>("tmp")
  const [scatterY, setScatterY]               = useState<string>("press")

  const [activeTime, setTime] = useState<number>(5)
  const [nTimes    , setNTimes] = useState<number>(11)

  useEffect(() => {
    const fetchFieldList = async () => {
      const newFields = await Intermediary.getFields()
      setFieldsList(newFields)

      // Update Scatter
      const newScatter = await Intermediary.getScatter(scatterX, scatterY)
      setScatter(newScatter.data)

      // Update Hmat
      const pt   = 4
      const time = 6
      const newHmat = await Intermediary.getHmat(pt, time)
      setHmat(newHmat.data)
    }
    fetchFieldList()
  }, [])

  function GridPointSelector() {

    function handleClick() {
      const pt   = 4
      const time = 6
      
      // Update Scatter
      Intermediary.getScatter(scatterX, scatterY).then((response: any) => {
        // console.log("scatter promise: ", response.data)
        setScatter(response.data)
      })
      .catch((e: Error) => {
        console.log(e)
      })

      // Update Hmat
      Intermediary.getHmat(pt, time).then((response: any) => {
        setHmat(response.data)
      })
      .catch((e: Error) => {
        console.log(e)
      })

    }

    return (
      <button 
        type="button" 
        className="btn btn-outline-primary btn-sm"
        onClick={() => handleClick()}>
        Select grid point
      </button>
    )
  }

  return (
    <>
    {/* <Nav>
      <div className="col-auto navcol">
        <TemporalOptions fields={fieldsList} data={temporalPanelData} setData={setTempPanelData}/>
      </div>
      <div className="col-auto navcol">
        <TimeBtn activeTime={activeTime} nTimes={nTimes} setTime={setTime}/>
      </div>
    </Nav> */}
    <Main>
      <div className="analyzes">
        <div className="spatial">
        {/* {GridPointSelector()} */}
          <Map time={activeTime} setTime={setTime}/>
        </div>
        {/* <div className="temporal overflow-auto">
          <div className="container">
            <TemporalPanel fields={fieldsList} timeSeries={temporalPanelData} activeTime={activeTime} />
          </div>
        </div>
        <div className="corr">
          <div className="m-2">
            <HmatPanel data={hmat}/>
          </div>
        </div>
        <div className="bias">
          <div className="m-2">
            <ScatterPanel fields={fieldsList} data={scatter} setScatter={setScatter}/>
          </div>
        </div> */}
      </div>
    </Main>
    </>
  )
}

export { Home }
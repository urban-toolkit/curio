import { VegaLite } from 'react-vega'
import { VisualizationSpec } from 'vega-embed'

interface HmatPanelProps {
  data: any[]
}

const HmatPanel = ({ data }: HmatPanelProps) => {

  if (data.length === 0) {
    // return <div>No data yet</div>  
    return <div></div>  
  } 

  const hmat: VisualizationSpec = {
    "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
    "width": 420,
    "data": { "values": data },

    "title": "Correlations",
    
    "config": {
      "view": {
        "strokeWidth": 0,
        "step": 36
      },
      "axis": {
        "domain": false
      }
    },

    "mark": "rect",
    
    "encoding": {
      "x": {
        "field": "socioField",
        "type": "nominal",
        "title": "",
      },

      "y": {
        "field": "atmField",
        "type": "nominal",
        "title": ""
      },

      "color": {
        "field": "corr",
        "type": "quantitative",
        "legend": {
          "title": "",
        }
      },
    }
  }

  return(
    <>
    <div>
      <VegaLite
        spec={hmat}
        actions={false}
        renderer={'svg'}
      />
    </div>
    </>
  )

}

export { HmatPanel }